# Lane C: the site editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer edits a Puck **site** document inside the chat shell: the canvas runs on a per-workspace editor domain inside one sandboxed iframe, while fields, Layers, pages, versions, images and annotations stay in the app's designed chrome, and every save goes through the app with the marketer's login.

**Architecture:** A new `site` kind flows through the frontend's kind switch (Contract 8). A small static single-page editor app (`apps/frontend/packages/site-editor`: an esbuild browser bundle plus a ~200-line `node:http` server) is served on `https://<label>.<CLUE_SITE_EDITOR_SUFFIX>` with a strict nonce CSP; it renders only `Puck.Preview`, loads agent sections through its own token-verified `/sections/<digest>.mjs` route, proxies `/asset-store/<sha>` on its own origin, and speaks the Zod protocol in `@clue/site-kit/editor-protocol` (Contract 6). The app mounts it as a persistent frame in the stage, holds the site JSON, draws fields and Layers with the inspector primitives, and saves through the design API's site routes (Contract 2) via the BFF.

**Tech Stack:** Next 16.2.12 (App Router), React 19.2.4, TypeScript 5, Zod 4.4.3, Tailwind 4 (`@tailwindcss/postcss` + `postcss` 8.5.23), `@puckeditor/core` 0.23.0, esbuild 0.28.2, Node 22 (`node:http`, `node:test` through `tsx`), jsdom 29, Python Playwright 1.61 in the repo `.venv`.

**Spec:** `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` — sections "Global constraints", "Review focus", "D2", and "Wave 2: rulings and cross-lane contracts (2026-10-11)" (Contracts 1–9). This plan implements Contract 6, the frontend half of Contract 8 and the editor half of Contract 9, and consumes Contracts 1, 2, 4 and 7. Code survey with file:line evidence: `/private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-trenton/59930c58-23dc-404a-b838-da2b3398b95b/scratchpad/wave2-survey-lane-c.md`. Reference spike: `trials/puck-spike/` (frozen; never edited except Task 16's new spike page).

---

## Open questions for the founder

Each question has a recommendation. The plan's code implements the recommendation and names the step to drop or change if the answer differs. Nothing here blocks Tasks 1–8.

- **Q1 — ANSWERED 2026-10-12: `edit.deeppresence.ai`** (founder: nothing else runs on
  deeppresence.ai, so no login shares the registrable domain). Each workspace's editor is
  `https://<label>.edit.deeppresence.ai`; `.env.example` defaults to it, as `CLUE_PAGES_SYSTEM_SUFFIX`
  already defaults to its production value. Original question: **The editor's registrable domain.** Contract 9 needs `CLUE_SITE_EDITOR_SUFFIX` in production; the name is the founder's to register.
  - (a) A new registrable domain used only for editing (for example `<name>-edit.com`), wildcard DNS + wildcard certificate on it. **Recommended** — it is what D2 decided (separate registrable domain, one subdomain per workspace).
  - (b) A subdomain of the new published-pages domain. Not recommended: D2 keeps the published-pages domain distinct from the editor domain.
  - Until answered, `.env.example` ships `CLUE_SITE_EDITOR_SUFFIX=` (empty) and a site in production shows the canvas's existing error state with "The website editor is not configured for this environment." Dev uses `editor.localhost:<port>` (Task 15).
- **Q2. Repeating fields (stats, nav links, list items) in the dock.** No designed control exists.
  - (a) Show each existing item's fields in place, grouped under "<Field label> <n>", with no add/remove. **Recommended** (Task 9 implements this).
  - (b) Hide repeating fields until designed.
  - (c) Add/remove item controls — needs a design first.
- **Q3. Share, Publish and Export for sites before Lane A's A7 (publish) and A8 (export) land.**
  - (a) Treat `site` exactly like `web` in the Share menu and the library's export (one rule, `isWebsiteKind`). **Recommended**: no workspace is in the site flag until Wave 4, so nobody sees a backend refusal in between, and nothing has to be re-wired later. Task 2 Step 9 implements it.
  - (b) Hide Share/Export for sites until A7/A8 land. If chosen, drop Task 2 Step 9 and keep the `kind === "web"` checks.
- **Q4. Version rows in the action menu.** The designed submenu shows "Current version / Version N".
  - (a) Keep exactly those labels, newest first (Task 13). **Recommended.**
  - (b) Also show who made each version (the agent or a person) and when — needs a design.
- **Q5. Highlighting a selected header or footer on the canvas.** Puck draws its own outline for page sections, but the shell is not a Puck component.
  - (a) A 2px outline in Puck's own selection blue (`--puck-color-azure-04`) on the selected header/footer. **Recommended** (Task 6 adds it; listed as design review point DR5).
  - (b) No highlight; the dock title alone says "Header".
- **Q6. A route typed into the URL bar that is not a page.**
  - (a) Put the current route back and say nothing (the W3.3 ruling bars new failure UI). **Recommended** (Task 14).
  - (b) Show a line under the bar — needs a design.

## Contract conflicts

None of the contracts is impossible. These are gaps or refinements; each names the owner and what this plan assumes. The ones marked **(blocking for live use)** must be answered by Lane A/B before a real site opens in the editor; the plan's fixture repository and the browser harness run without them.

- **K1 (Contract 4 gap, owner B6, blocking for live use).** Contract 4 says the editor server "verifies the token with the design API" but names no route, and the per-module CSS (`css_sha256`, stored per RUNTIME-SECTIONS finding 5) has no delivery route. **Assumed:** two public, headerless, token-authenticated design-API routes — `GET /site-sections/{digest}.mjs?t=<token>` (200 `text/javascript`, the module bytes) and `GET /site-sections/{digest}.css?t=<token>` (200 `text/css`; an empty body when the module has no CSS) — each answering with the response header `X-Clue-Workspace-Id: <workspace id>` so the editor server can check that the module belongs to the workspace whose label is in its `Host` (Review focus 4 of the master plan, tenant isolation). Any other status means "refuse".
- **K2 (Contracts 4 × 6, owner B6, blocking for live use).** Contract 6's `init` carries `propsSchema` per section, but Contract 4's `POST /documents/{id}/site/section-links` returns only `[{name, digest, token, expires_at}]`. **Assumed:** the response is `{"links": [{name, digest, token, expires_at, props_schema}]}`, with `props_schema` taken from `design_site_section.props_schema_json`.
- **K3 (Contract 6 gap, owner B (kit → BrandData) serving through A's design API, blocking for live use).** Contract 6's `init` carries `brand: BrandData`, but no contract names the read that gives the app a site's `BrandData`. **Assumed:** `GET /documents/{id}/site/brand` → `{"brand": BrandData}`, with every asset and font `file` as `/asset-store/<sha256>`.
- **K4 (Contract 2 gap, owner A1/A2, blocking for live use).** Contract 2 lists writes only. **Assumed:** the existing `GET /documents/{id}` answers a site document with `doc_kind: "site"`, `scene` = the Contract 1 site, `current_version`, and `undo_stack`/`redo_stack` arrays (as it does for web documents), without the scene-only `render_context` (today `lumen_api/main.py:2606` computes it for every non-web document — A1's kind-branch audit). Also `GET /documents/{id}/agent-run` must answer for site documents (the artifact route's lock reads it).
- **K5 (Contract 1 refinement, owner A0/A2).** Annotation object ids are `site:<route>#<componentId>.<prop>` (Contract C7/A3). A component id containing `#` or `.` would make that string ambiguous. **Assumed and enforced at the protocol seam:** component ids match `^[A-Za-z0-9_-]{1,200}$`; the site-kit validator should refuse anything else.
- **K6 (Contract 6 additions, owner Lane C, recorded in the master plan at the controller review; Task 4 Step 7 checks it).** Three additive refinements, none product-facing: (1) frame → app `shortcut {action: "undo" | "redo"}` — ⌘Z/⇧⌘Z pressed while focus is in the frame, because Puck's in-frame history is not the source of undo; (2) `route` in `selected`, `annotate`, `request_asset`, `set_props`, `select` and `insert_asset` may be the literal `"shell"` for the header/footer, which is exactly what makes the C7 object id `site:shell#header`; (3) the frame posts `navigated {route}` once after it has applied an `init`, which the app uses as "the frame now shows this document".
- **K7 (Contract 2 note, owner A2).** The save response `{document: {id, current_version, doc_kind}}` carries no stack depths. **Assumed:** the app counts one undo step per successful save (capped at 50) and re-reads the true depths from `GET /documents/{id}` on every reload.

### Controller review resolution (2026-10-11)

Every assumption above is now a commitment in another lane's plan or in the master plan, exactly as
assumed here:

- **K1** → Lane B Task 16 serves `GET /site-sections/{digest}.mjs?t=` and `.css?t=` (empty CSS when
  the module has none), headerless and token-gated, each answering `x-clue-workspace-id` (ruling R2).
- **K2** → Lane B Task 16 answers `{"schema_version": 1, "links": [{name, digest, token, expires_at,
  props_schema}]}` (ruling R1).
- **K3** → Lane A Task 13 adds `GET /documents/{id}/site/brand` → `{"schema_version": 1, "brand":
  BrandData}` through the brand-loader seam (503 `site_inputs.unavailable` until Lane B2; ruling R3).
- **K4** → Lane A Task 8 (no `render_context` for a site; the stacks ride as for web);
  `GET /documents/{id}/agent-run` is already kind-agnostic (`lumen_api/main.py:2615`).
- **K5** → Lane A Task 6 adds the same id rule to the site-kit validator, so no stored site can carry
  an id this editor's schema refuses (ruling R10).
- **K6** → recorded in the master plan's Contract 6 at the review; Task 4 Step 7 only checks it.
- **K7** → no contract change: the web lane also counts between loads and re-reads the stacks on
  load (`engine/webDocuments.ts:389`, `hooks/use-web-editing-session.ts:556`).

## Design review points

Built from existing chat-shell styles and primitives; where no existing style fits, the plan uses the closest existing tokens and records the point here instead of inventing a look. Each is marked `DESIGN REVIEW` in the code comment that implements it.

- **DR1** The Pages toggle's placement: first item of the header's action group (Ploy puts it at the far left of the toolbar). Uses `.artifactActionButton` + `.artifactActionButtonActive` and lucide `FilesIcon`.
- **DR2** The page panel: 280px column left of the canvas; container, head and list classes are new (`.sitePagesPanel*`) but use only `--chat-shell-*` tokens; rows reuse `.layerRow*`; search reuses `InspectorInput`; the count reuses `.inspectorFieldLabel`.
- **DR3** The URL toolbar: back/forward reuse `.deviceButton`; the route field is a new `.siteUrlField` built from `.artifactHeadingRenameInput`'s tokens; reload reuses `.deviceButton`; the existing device menu is moved inside the bar unchanged.
- **DR4** The dock's section label "Content" for a selected site section (the web lane says "Component properties", which the marketer must not see).
- **DR5** The header/footer selection outline on the canvas (Q5).
- **DR6** Repeating fields grouped as "<label> <n>" (Q2).
- **DR7** An image field: the existing "Replace image" pill (`InspectorImageUpload`) with the ad lane's generate rows (`AdImageAiRows`) stacked under it.

## Global Constraints

- **Git:** never push. Commit locally at the end of each task, with no AI attribution in messages (no `Co-Authored-By`, no "Generated with"). Work stays on the feature branch (`puck/integration-wave1` or its successor), never `main`.
- **Env parity:** every new runtime setting goes into `.env.example` with its default the moment it is introduced; a frontend setting also into `apps/frontend/.env.example`; the editor app's settings into `apps/frontend/packages/site-editor/.env.example`. The local `.env` keeps full key parity (`.env` is untracked: edit it, never commit it).
- **WebDoc stays untouched.** With no site document open, every existing web and ad path behaves byte-identically. No old-lane gate may block the new lane.
- **Founder rulings:** the marketer never sees "clones" or "components"; the editor UI comes only from the existing chat-shell / dummy UI, so new controls need a design first (see "Design review points").
- **Agent-written code never runs on app.cluehq.ai or in a platform process (D2):** in the browser only on the editor domain. Node only transforms or scans agent code (esbuild, tsc, Tailwind); it never imports or runs it. Task 15's probe compiler bundles the hostile probes with esbuild and never imports the output.
- **Frame:** `<iframe sandbox="allow-scripts allow-same-origin">`, no `allow-top-navigation`, no popups, `referrerPolicy="no-referrer"`.
- **Editor CSP:** `script-src 'self' 'nonce-<per response>'` — no `'unsafe-eval'`, no `'strict-dynamic'`, no `blob:`; the only inline script is the nonced import map; `frame-ancestors` = the app origin exactly; `img-src`/`font-src` `'self' data:`, `media-src 'self'` (the editor's own `/asset-store` proxy); `connect-src 'self'`; zod runs jitless.
- **Editor protocol (Contract 6):** every message is `{channel: "clue-site-editor", v: 1, documentId, nonce, type, payload}`; the app checks `event.origin` against the workspace's exact editor origin, `event.source`, the nonce and the document id; the frame checks `event.source === window.parent` and the app origin. **No `"*"` target origin anywhere.**
- **Engineering rulings already made:** selection reaches chat as annotation chips (web-lane pattern); the agent-run lock applies to sites; Puck's in-frame history is not the source of undo (the server stack is); the app holds the site JSON and is the only side that saves; the editor label is an opaque token derived from the workspace id; the editor's img/font/media sources are its own origin's `/asset-store` proxy.
- **The save policy is the web lane's:** one save in flight, the base version in a ref, a 409 shows exactly `Document moved on — reloaded.` and reloads (the edit is dropped).
- **Contract 8 order:** Task 2 must be committed before Lane A's mapper starts sending `"site"`; until both land no workspace is in `CLUE_DESIGN_SITE_ENGINE_WORKSPACES`.
- **Next.js:** "This is NOT the Next.js you know" (`apps/frontend/AGENTS.md`). Before writing a route handler, read `apps/frontend/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/route.md`.
- **Tests:** frontend unit tests are `node:test` files under `apps/frontend/src/**/*.test.ts`, run with `npx tsx --test <file>` (all of them: `npm test`); package tests run with `npm test -w <package>`. Never run `*_live.py` or broad suites with real keys; browser tests are gated by an env var.
- **The frontend check gate** runs before every commit that touches `apps/frontend`, from `apps/frontend`: `npm run design-system:build && npm run lint && npm run build`. Expected: three commands exit 0; `next build` ends with the route table and no type errors.

## Review Focus

Each line names an input or condition no task's happy-path tests cover, the behaviour a person would expect, and where its pinning test lives.

1. **A message from the wrong window or a stale frame** — another tab's editor, an agent section calling `parent.postMessage({type: "puck:publish"}, "*")`, a frame reloaded with a new nonce — is dropped on both sides. Pinned by Task 4 (`acceptAppMessage` / `acceptFrameMessage` refusal table).
2. **Switching between two sites (or site → web → site) while the frame stays warm** re-initialises the frame with the new document, and messages still tagged with the old document id never touch the new one. Pinned by Task 8 (`frameSyncFor` and the session's document-id guard).
3. **A save racing the agent:** the agent's checkpoint lands between two of the user's edits; the next save is refused 409 and the canvas shows the agent's version with "Document moved on — reloaded." Pinned by Task 3 (controller) and Task 8 (reload sends `replace_site`).
4. **Section links past their 10-minute life on a frame re-init** (the frame reloaded after the tab sat open): the app fetches fresh links before it sends `init`. Pinned by Task 8 (`linksFresh`).
5. **Edit mode off, or the agent-run lock on:** the app ignores `changed` from the frame and never saves, and the frame is put in preview. Pinned by Task 8 (`acceptsFrameEdits`, `siteFrameMode`) and Task 12 (the lock's other effects: the dock disabled, undo refused).

The master plan's own Review focus 1 (a site never reaches a scene path) is pinned in Task 2, and its Review focus 6 (agent sections contained by the editor domain) in Task 15.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `apps/frontend/Dockerfile.railway` | copy every workspace manifest before `npm ci` | 1 |
| `tests/deploy/test_frontend_image.py` | guard: every `packages/*/package.json` is copied before `npm ci` | 1 |
| `apps/frontend/src/features/design-editor/model/artifact.ts` | `DesignDocumentKindSchema` (`web`/`ad`/`site`) on the wire | 2 |
| `apps/frontend/src/features/chat-shell/model/artifact-kind.ts` | `isWebsiteKind`, `chatShellKindForCard` — the one kind derivation | 2 |
| `apps/frontend/src/features/chat-shell/model/{chat-shell,chat-dock,chat-surface-params,gallery-card-target,open-artifact-param,artifact-auto-open}.ts` | `site` through every mapping | 2 |
| `apps/frontend/src/features/{design-editor/adapter/gallery,artifacts/model/artifact-library,projects/model/project-workspace}.ts` | `documentKind` on gallery/library cards | 2 |
| `apps/frontend/src/features/design-editor/engine/scene/documentStore.ts` | the scene loader refuses a site | 2 |
| `apps/frontend/packages/site-kit/src/site-document.ts` | Contract 1 Zod schemas (`SiteDocumentSchema`, `BrandDataSchema`, `SectionLinkSchema`, targets) | 3 |
| `apps/frontend/src/features/site-editor/model/site-wire.ts` | wire schemas for the site reads/writes | 3 |
| `apps/frontend/src/features/site-editor/data/site.repository.ts` | `SiteRepository` (HTTP via BFF + fixture with CAS) | 3 |
| `apps/frontend/src/features/site-editor/hooks/site-save-controller.ts` | the pure save policy | 3 |
| `apps/frontend/src/features/site-editor/hooks/use-site-saves.ts` | React binding of the controller | 3 |
| `apps/frontend/packages/site-kit/src/{editor-protocol,editor-site,editor-origin}.ts` | Contract 6 messages + acceptors; shared site edits; editor label/origin | 4 |
| `apps/frontend/packages/site-editor/` | the editor app (server, client, build, tests, Dockerfile) | 5, 6, 15 |
| `apps/frontend/src/app/api/clue/site-editor/session/route.ts` + `src/features/site-editor/server/site-editor-session-handler.ts` | the workspace's editor origin for the browser | 7 |
| `apps/frontend/src/features/site-editor/{model,hooks}/*` | canvas state, frame sync, document load, frame host, editing session | 8–14 |
| `apps/frontend/src/features/design-editor/components/{canvas-states,site-artifact-canvas}.tsx` | the web canvas's three states, shared; the site frame host | 8 |
| `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` | persistent warm site stage | 8, 11, 14 |
| `apps/frontend/src/features/chat-shell/components/{site-inspector,site-pages-panel,site-url-bar}.tsx` | dock fields + Layers; page panel; URL toolbar | 9, 10, 14 |
| `apps/frontend/src/features/chat-shell/components/{chat-surface,editor-surface,artifact-header,artifact-action-menu}.tsx` | wiring | 2, 8–14 |
| `scripts/dev_stack.sh`, `scripts/dev_stack_trenton.sh`, `DEV_STACK.md`, `.env.example`, `apps/frontend/.env.example`, `apps/frontend/docs/railway-deployment.md` | dev stack and deploy | 15 |
| `tests/site_editor/` | browser harness (renders test, containment test) | 6, 15 |
| `trials/puck-spike/app/r5-richtext/`, `trials/puck-spike/RICHTEXT-R5.md` | R5 spike | 16 |

---

### Task 1: C0 — the Railway build installs every workspace package

The frontend is an npm workspace rooted at `apps/frontend` (`"workspaces": ["packages/*"]`). `npm ci` in the image's `dependencies` stage sees only the manifests copied before it, and today it copies `packages/design-system/package.json` alone (`apps/frontend/Dockerfile.railway:10-12`), not the Wave 1 `@clue/site-kit`. Task 5 adds a third package; the guard below makes the next one impossible to forget.

**Files:**
- Modify: `apps/frontend/Dockerfile.railway:9-12`
- Create: `tests/deploy/test_frontend_image.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/deploy/test_frontend_image.py::DOCKERFILES` (a list of repo-relative Dockerfile paths). Task 15 appends `apps/frontend/packages/site-editor/Dockerfile.railway` to it.

- [ ] **Step 1: Write the failing guard test.**

`tests/deploy/test_frontend_image.py`:
```python
"""Lane C task C0: every frontend image installs every npm workspace package.

`npm ci` runs in the image's dependencies stage before the sources are copied, so each workspace
package's manifest must be copied first or the package is silently missing from node_modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGES = REPO / "apps/frontend/packages"
DOCKERFILES = ["apps/frontend/Dockerfile.railway"]


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_every_workspace_manifest_is_copied_before_npm_ci(dockerfile: str) -> None:
    text = (REPO / dockerfile).read_text(encoding="utf-8")
    assert "RUN npm ci" in text, f"{dockerfile} no longer runs npm ci"
    before_install = text.split("RUN npm ci", 1)[0]
    manifests = sorted(PACKAGES.glob("*/package.json"))
    assert manifests, "no workspace packages found"
    for manifest in manifests:
        relative = manifest.relative_to(REPO).as_posix()
        assert f"COPY {relative} " in before_install, f"{dockerfile} does not copy {relative} before npm ci"
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `.venv/bin/python -m pytest tests/deploy/test_frontend_image.py -q`
Expected: FAIL — `apps/frontend/Dockerfile.railway does not copy apps/frontend/packages/site-kit/package.json before npm ci`.

- [ ] **Step 3: Copy the site-kit manifest before `npm ci`.**

In `apps/frontend/Dockerfile.railway`, replace lines 9-12:
```dockerfile
# Install from the frontend lockfile. The design-system package manifest is
# needed because the frontend is an npm workspace rooted here.
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/design-system/package.json ./packages/design-system/package.json
```
with:
```dockerfile
# Install from the frontend lockfile. The frontend is an npm workspace rooted
# here, so EVERY workspace package's manifest must be copied before `npm ci`
# (tests/deploy/test_frontend_image.py enforces it).
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/design-system/package.json ./packages/design-system/package.json
COPY apps/frontend/packages/site-kit/package.json ./packages/site-kit/package.json
```

- [ ] **Step 4: Run the guard again.**

Run: `.venv/bin/python -m pytest tests/deploy/test_frontend_image.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Prove the image's install stage works.** (Docker Desktop must be running; if it is not, start it rather than skipping this step.)

Run from the repo root: `docker build --target dependencies -f apps/frontend/Dockerfile.railway -t clue-frontend-deps-check .`
Expected: the build ends with `naming to docker.io/library/clue-frontend-deps-check` and no `npm error`. Then `docker image rm clue-frontend-deps-check`.

- [ ] **Step 6: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 7: Commit.**
```bash
git add apps/frontend/Dockerfile.railway tests/deploy/test_frontend_image.py
git commit -m "frontend image: copy the site-kit workspace manifest before npm ci, with a guard for every workspace package"
```

---

### Task 2: C1 — the `site` kind across the frontend (lands before Lane A's mapper, Contract 8)

A `"site"` on the wire fails the Zod parse today (`design-editor/model/artifact.ts:17,31`, `artifacts/model/artifact-library.ts:14`), and every mapping that rebuilds a kind from the gallery's `website`/`canvas` vocabulary turns anything that is not a website into an ad (survey C1 table). This task makes `site` a first-class kind: the wire accepts it, gallery and library cards remember their document kind (`documentKind`), every place that derives a kind uses one helper, the URL surface is `surface=site`, the dock content is `"site-inspector"`, the stage shows the website pane (empty until Task 8), and the scene loader refuses a site document outright.

A site card stays a **website** card in the gallery (type `website`, collateral `microsite`): to the marketer a site is a website, and the composer's `@` lists it under Microsites with no change.

**Files:**
- Create: `apps/frontend/src/features/chat-shell/model/artifact-kind.ts`
- Create: `apps/frontend/src/features/chat-shell/model/site-kind.test.ts`
- Create: `apps/frontend/src/features/design-editor/adapter/gallery-site.test.ts`
- Create: `apps/frontend/src/features/artifacts/model/artifact-library-site.test.ts`
- Create: `apps/frontend/src/features/design-editor/engine/scene/document-store-site.test.ts`
- Create: `apps/frontend/src/features/projects/model/composer-context-catalog-site.test.ts`
- Modify: `apps/frontend/src/features/design-editor/model/artifact.ts:17,31`
- Modify: `apps/frontend/src/features/chat-shell/model/chat-shell.ts:1`
- Modify: `apps/frontend/src/features/projects/model/project-workspace.ts:125-155` (`ProjectArtifactSchema`)
- Modify: `apps/frontend/src/features/design-editor/adapter/gallery.ts:108-140` (`toProjectArtifact`)
- Modify: `apps/frontend/src/features/artifacts/model/artifact-library.ts:14,54,76-110`
- Modify: `apps/frontend/src/features/chat-shell/model/gallery-card-target.ts`
- Modify: `apps/frontend/src/features/chat-shell/model/open-artifact-param.ts`
- Modify: `apps/frontend/src/features/chat-shell/model/artifact-auto-open.ts:18-25,68`
- Modify: `apps/frontend/src/features/chat-shell/model/chat-dock.ts:26-42`
- Modify: `apps/frontend/src/features/chat-shell/model/chat-surface-params.ts:26-40,99-106`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx:62-64,87`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-header.tsx:220`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx:405,470-560`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx:1239-1258` (gallery open)
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx:335-341` (gallery open)
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.ts:207,315,366,408`
- Modify: `apps/frontend/src/features/projects/components/chat-message-reference.tsx:54`
- Modify: `apps/frontend/src/features/design-editor/engine/scene/contracts.ts:34`
- Modify: `apps/frontend/src/features/design-editor/engine/scene/documentStore.ts:147-175`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `design-editor/model/artifact.ts`: `export const DesignDocumentKindSchema = z.enum(["web", "ad", "site"]); export type DesignDocumentKind = z.infer<typeof DesignDocumentKindSchema>;`
  - `chat-shell/model/chat-shell.ts`: `export type ChatShellArtifactKind = DesignDocumentKind;` (so `"ad" | "web" | "site"`).
  - `chat-shell/model/artifact-kind.ts`: `isWebsiteKind(kind: string | null | undefined): kind is "web" | "site"` and `chatShellKindForCard(card: { type?: ProjectArtifact["type"]; documentKind?: DesignDocumentKind }): ChatShellArtifactKind`.
  - `ProjectArtifact.documentKind?: DesignDocumentKind` (set by `toProjectArtifact` and `toLibraryArtifact`).
  - `ChatDockContent = "ad-inspector" | "conversation" | "web-inspector" | "site-inspector"`.
  - `documentStore.ts`: `export const SITE_DOCUMENT_IN_SCENE_EDITOR: string` and `fetchDocument` throws `new Error(SITE_DOCUMENT_IN_SCENE_EDITOR)` for `doc_kind: "site"`.

- [ ] **Step 1: Write the failing kind tests.**

`apps/frontend/src/features/chat-shell/model/site-kind.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactsToAutoOpen } from "./artifact-auto-open";
import { chatShellKindForCard, isWebsiteKind } from "./artifact-kind";
import { chatDockContent } from "./chat-dock";
import { chatSurfacePaneParams, chatSurfaceUrlState } from "./chat-surface-params";
import { galleryCardTarget } from "./gallery-card-target";
import { openArtifactFromParam } from "./open-artifact-param";

// Contract 8: "site" is a kind of its own everywhere a kind travels. A card that
// carries its document kind opens in exactly that editor; a card without one keeps
// the gallery's historical derivation (website → web, anything else → ad).

test("a card that carries its document kind opens in that editor", () => {
  assert.equal(chatShellKindForCard({ type: "website", documentKind: "site" }), "site");
  assert.equal(chatShellKindForCard({ type: "website", documentKind: "web" }), "web");
  assert.equal(chatShellKindForCard({ type: "canvas", documentKind: "ad" }), "ad");
});

test("a card without a document kind keeps the historical derivation", () => {
  assert.equal(chatShellKindForCard({ type: "website" }), "web");
  assert.equal(chatShellKindForCard({ type: "canvas" }), "ad");
  assert.equal(chatShellKindForCard({}), "ad");
});

test("a site is a website to the marketer", () => {
  assert.equal(isWebsiteKind("site"), true);
  assert.equal(isWebsiteKind("web"), true);
  assert.equal(isWebsiteKind("ad"), false);
  assert.equal(isWebsiteKind("scene"), false);
  assert.equal(isWebsiteKind(null), false);
});

test("the gallery, ?open= and auto-open all route a site card to the site editor", () => {
  assert.deepEqual(
    galleryCardTarget({ id: "a1", title: "Landing", type: "website", documentKind: "site" }),
    { artifact: { id: "a1", kind: "site", title: "Landing" }, surface: "artifact" },
  );
  assert.deepEqual(
    openArtifactFromParam({
      openId: "a1",
      artifacts: [{ id: "a1", title: "Landing", type: "website", documentKind: "site" }],
    }),
    { id: "a1", kind: "site", title: "Landing" },
  );
  assert.deepEqual(
    artifactsToAutoOpen({
      activeThreadId: "t1",
      artifacts: [
        {
          documentKind: "site",
          id: "a1",
          originThreadId: "t1",
          title: "Landing",
          type: "website",
          updatedAt: "2026-10-11T09:00:00.000Z",
        },
      ],
      knownArtifactIds: new Set(),
    }),
    [{ id: "a1", kind: "site", title: "Landing" }],
  );
});

test("editing a site docks the site inspector, never the ad inspector", () => {
  assert.equal(
    chatDockContent({ artifactKind: "site", editing: true, panelOpen: true, surface: "artifact" }),
    "site-inspector",
  );
  assert.equal(
    chatDockContent({ artifactKind: "site", editing: false, panelOpen: true, surface: "artifact" }),
    "conversation",
  );
});

test("surface=site round-trips through the pane vocabulary", () => {
  const parsed = chatSurfaceUrlState({ surface: "site", edit: "1" });
  assert.equal(parsed.surface, "artifact");
  assert.equal(parsed.editing, true);
  assert.deepEqual(
    chatSurfacePaneParams({
      artifactKind: "site",
      editing: true,
      inspectorSelection: "canvas",
      panelOpen: true,
      rawSurface: undefined,
      surface: "artifact",
    }),
    { edit: "1", selection: undefined, surface: "site" },
  );
  // A deep link that lands on the artifact surface before its tab exists keeps "site".
  assert.equal(
    chatSurfacePaneParams({
      artifactKind: null,
      editing: false,
      inspectorSelection: "canvas",
      panelOpen: true,
      rawSurface: "site",
      surface: "artifact",
    }).surface,
    "site",
  );
});
```

`apps/frontend/src/features/design-editor/adapter/gallery-site.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { DesignArtifactListItemSchema, DesignArtifactListWireSchema } from "../model/artifact";
import { toProjectArtifact } from "./gallery";

const NOW = new Date("2026-10-11T12:00:00Z");

function item(kind: "web" | "ad" | "site") {
  return DesignArtifactListItemSchema.parse({
    id: `art-${kind}`,
    projectId: "prj-1",
    documentId: `doc-${kind}`,
    kind,
    title: `A ${kind} document`,
    currentVersionId: "3",
    status: "draft",
    createdAt: "2026-10-11T09:00:00+00:00",
    updatedAt: "2026-10-11T10:00:00+00:00",
    originThreadId: "thread-1",
  });
}

test("the feed wire accepts a site document (Contract 8)", () => {
  const [parsed] = DesignArtifactListWireSchema.parse({
    data: [
      {
        id: "art-1",
        project_id: "prj-1",
        document_id: "doc-1",
        kind: "site",
        title: "Syracuse",
        status: "draft",
        current_version_id: "3",
        created_at: "2026-10-11T09:00:00+00:00",
        updated_at: "2026-10-11T10:00:00+00:00",
        origin_thread_id: "thread-1",
      },
    ],
  });
  assert.equal(parsed.kind, "site");
});

test("a site card is a website microsite that remembers it is a site", () => {
  const card = toProjectArtifact(item("site"), { now: NOW });
  assert.equal(card.type, "website");
  assert.equal(card.collateralType, "microsite");
  assert.equal(card.documentKind, "site");
});

test("web and ad cards carry their own document kind", () => {
  assert.equal(toProjectArtifact(item("web"), { now: NOW }).documentKind, "web");
  assert.equal(toProjectArtifact(item("ad"), { now: NOW }).documentKind, "ad");
});
```

`apps/frontend/src/features/artifacts/model/artifact-library-site.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { ArtifactWireSchema, toLibraryArtifact } from "./artifact-library";

test("a site row in the artifacts library is a website that remembers it is a site", () => {
  const row = ArtifactWireSchema.parse({
    id: "art-1",
    document_id: "doc-1",
    project_id: "prj-1",
    project_title: "Syracuse ABM",
    kind: "site",
    title: "Syracuse",
    status: "draft",
    current_version: 3,
    created_at: "2026-10-11T09:00:00+00:00",
    updated_at: "2026-10-11T10:00:00+00:00",
    origin_thread_id: "thread-1",
    artifact_type: null,
    width_px: null,
    height_px: null,
    account: null,
    archived_at: null,
    saved: false,
    last_viewed_at: null,
  });
  const artifact = toLibraryArtifact(row, new Date("2026-10-11T12:00:00Z"));
  assert.equal(artifact.kind, "site");
  assert.equal(artifact.type, "website");
  assert.equal(artifact.collateralType, "microsite");
  assert.equal(artifact.documentKind, "site");
});
```

`apps/frontend/src/features/design-editor/engine/scene/document-store-site.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchDocument, SITE_DOCUMENT_IN_SCENE_EDITOR } from "./documentStore";

// Master plan Review focus 1: a site document must never reach a scene-only path.
test("the scene loader refuses a site document instead of drawing it as an ad", async () => {
  const fetchImpl = (async () =>
    new Response(
      JSON.stringify({
        id: "doc-1",
        doc_kind: "site",
        title: "Syracuse",
        scene: { id: "doc-1", pages: { "/": { root: { props: {} }, content: [] } } },
        current_version: 2,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    )) as typeof fetch;
  await assert.rejects(
    fetchDocument({ apiBaseUrl: "http://design.test", fetchImpl }, "doc-1"),
    (error: unknown) => error instanceof Error && error.message === SITE_DOCUMENT_IN_SCENE_EDITOR,
  );
});
```

`apps/frontend/src/features/projects/model/composer-context-catalog-site.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildComposerCatalog } from "./composer-context-catalog";
import { ProjectArtifactSchema } from "./project-workspace";

test("a site lists in the composer exactly like a website: a Microsite design document", () => {
  const catalog = buildComposerCatalog({
    artifacts: [
      ProjectArtifactSchema.parse({
        collateralType: "microsite",
        documentId: "doc-1",
        documentKind: "site",
        editedLabel: "Last edited today",
        id: "art-1",
        originThreadId: "thread-1",
        title: "Syracuse",
        type: "website",
        version: 3,
      }),
    ],
    documents: [],
    entities: [],
  });
  assert.deepEqual(
    catalog.map((entity) => [entity.category, entity.secondaryLabel, entity.type, entity.id]),
    [["microsites", "Microsite", "design_document", "doc-1"]],
  );
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/model/site-kind.test.ts src/features/design-editor/adapter/gallery-site.test.ts src/features/artifacts/model/artifact-library-site.test.ts src/features/design-editor/engine/scene/document-store-site.test.ts src/features/projects/model/composer-context-catalog-site.test.ts`
Expected: FAIL — `Cannot find module './artifact-kind'` and Zod errors `Invalid option: expected one of "web"|"ad"`.

- [ ] **Step 3: Widen the wire enums.**

In `apps/frontend/src/features/design-editor/model/artifact.ts`, add below the `import { z } from "zod";` line:
```ts
/**
 * Contract 8 (Wave 2): every design document kind the wire carries. `site` is the
 * Puck site document (Lane A/B); it is a website to the marketer but opens in its
 * own editor, so nothing may fold it into `web` or `ad`.
 */
export const DesignDocumentKindSchema = z.enum(["web", "ad", "site"]);
export type DesignDocumentKind = z.infer<typeof DesignDocumentKindSchema>;
```
Then replace both `kind: z.enum(["web", "ad"]),` lines (in `ChatShellArtifactSchema` and `DesignArtifactItemWireSchema`) with `kind: DesignDocumentKindSchema,`.

In `apps/frontend/src/features/chat-shell/model/chat-shell.ts`, replace line 1 with:
```ts
import type { DesignDocumentKind } from "@/features/design-editor/model/artifact";

export type ChatShellArtifactKind = DesignDocumentKind;
```

In `apps/frontend/src/features/projects/model/project-workspace.ts`, add the import at the top of the file (with the other imports):
```ts
import { DesignDocumentKindSchema } from "@/features/design-editor/model/artifact";
```
and add this key to `ProjectArtifactSchema`, directly after `documentId: z.string().min(1).optional(),`:
```ts
  // The design document's own kind (Contract 8). Present on design artifacts so a
  // card opens in the right editor; `type` stays the gallery vocabulary, where a
  // site is a website. Absent on table/presentation cards and older sources.
  documentKind: DesignDocumentKindSchema.optional(),
```

- [ ] **Step 4: Write the one kind derivation.**

`apps/frontend/src/features/chat-shell/model/artifact-kind.ts`:
```ts
import type { DesignDocumentKind } from "@/features/design-editor/model/artifact";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { ChatShellArtifactKind } from "./chat-shell";

/**
 * Contract 8: the ONE place a gallery/library card becomes an editor kind.
 *
 * A card that carries its document kind opens in exactly that editor. A card
 * without one (an older source, a fixture) keeps the gallery's historical
 * derivation — `website → web`, anything else → `ad` — which is exactly what the
 * four call sites did inline before `site` existed.
 */
export function chatShellKindForCard(card: {
  documentKind?: DesignDocumentKind;
  type?: ProjectArtifact["type"];
}): ChatShellArtifactKind {
  if (card.documentKind) return card.documentKind;
  return card.type === "website" ? "web" : "ad";
}

/** A website to the marketer, whichever engine draws it. */
export function isWebsiteKind(kind: string | null | undefined): kind is "web" | "site" {
  return kind === "web" || kind === "site";
}
```

- [ ] **Step 5: Stamp `documentKind` on gallery and library cards.**

In `apps/frontend/src/features/design-editor/adapter/gallery.ts` `toProjectArtifact`, add `documentKind: item.kind,` directly after `documentId: item.documentId,` inside the `ProjectArtifactSchema.parse({ … })` call.

In `apps/frontend/src/features/artifacts/model/artifact-library.ts`:
- add `import { DesignDocumentKindSchema, type DesignDocumentKind } from "@/features/design-editor/model/artifact";` to the imports;
- replace `kind: z.enum(["web", "ad"]),` in `ArtifactWireSchema` with `kind: DesignDocumentKindSchema,`;
- replace `kind: "web" | "ad";` in `LibraryArtifact` with `kind: DesignDocumentKind;`;
- in `toLibraryArtifact`, add `documentKind: row.kind,` directly after `createdAt: utcInstant(row.created_at),` inside the `ProjectArtifactSchema.parse({ … })` call.

- [ ] **Step 6: Route every kind derivation through the helper.**

`apps/frontend/src/features/chat-shell/model/gallery-card-target.ts`: add `import { chatShellKindForCard } from "./artifact-kind";`; add `documentKind?: ProjectArtifact["documentKind"];` to `GalleryCardArtifact`; and replace
```ts
      // The gallery's own kind derivation, unchanged.
      kind: card.type === "website" ? "web" : "ad",
```
with
```ts
      // Contract 8: the card's own document kind, else the historical derivation.
      kind: chatShellKindForCard(card),
```

`apps/frontend/src/features/chat-shell/model/open-artifact-param.ts`: add `import { chatShellKindForCard } from "./artifact-kind";`; change the `artifacts` type to `readonly Pick<ProjectArtifact, "id" | "title" | "type" | "documentKind">[]`; and replace the return with
```ts
  return { id: match.id, kind: chatShellKindForCard(match), title: match.title };
```

`apps/frontend/src/features/chat-shell/model/artifact-auto-open.ts`: add `import { chatShellKindForCard } from "./artifact-kind";`; add `documentKind?: ProjectArtifact["documentKind"];` to `AutoOpenFeedArtifact`; and replace
```ts
      kind: artifact.type === "website" ? ("web" as const) : ("ad" as const),
```
with
```ts
      kind: chatShellKindForCard(artifact),
```

`apps/frontend/src/features/chat-shell/components/chat-surface.tsx` — in `onOpenGalleryArtifact`, add `documentKind: artifact.source?.documentKind,` to the object passed to `galleryCardTarget({ … })`.

`apps/frontend/src/features/chat-shell/components/editor-surface.tsx` — add `import { chatShellKindForCard } from "../model/artifact-kind";` and replace
```tsx
            kind: artifact.source?.type === "website" ? "web" : "ad",
```
with
```tsx
            kind: chatShellKindForCard({
              documentKind: artifact.source?.documentKind,
              type: artifact.source?.type,
            }),
```

- [ ] **Step 7: Dock and URL vocabulary.**

`apps/frontend/src/features/chat-shell/model/chat-dock.ts`: replace the `ChatDockContent` type and `chatDockContent` body with
```ts
/** What `.chatBody` renders. `"conversation"` is the resting state. */
export type ChatDockContent =
  | "ad-inspector"
  | "conversation"
  | "site-inspector"
  | "web-inspector";

export function chatDockContent(state: ChatDockState): ChatDockContent {
  if (!chatDockOpen(state)) return "conversation";
  if (state.artifactKind === "web") return "web-inspector";
  if (state.artifactKind === "site") return "site-inspector";
  return "ad-inspector";
}
```

`apps/frontend/src/features/chat-shell/model/chat-surface-params.ts`: replace `if (raw === "web" || raw === "ad") return "artifact";` with `if (raw === "web" || raw === "ad" || raw === "site") return "artifact";`, and replace
```ts
    (state.rawSurface === "web" || state.rawSurface === "ad"
      ? state.rawSurface
      : "web");
```
with
```ts
    (state.rawSurface === "web" || state.rawSurface === "ad" || state.rawSurface === "site"
      ? state.rawSurface
      : "web");
```

- [ ] **Step 8: Chrome: tabs, header icon, chat reference icon, scene contract.**

`apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx`: add `import { isWebsiteKind } from "../model/artifact-kind";`; replace both `name={kind === "web" ? "web-output" : "ad-canvas"}` with `name={isWebsiteKind(kind) ? "web-output" : "ad-canvas"}`, and replace `` aria-label={`Rename ${kind === "web" ? "web" : "image"} output`} `` with `` aria-label={`Rename ${isWebsiteKind(kind) ? "web" : "image"} output`} ``.

`apps/frontend/src/features/chat-shell/components/artifact-header.tsx`: add `import { isWebsiteKind } from "../model/artifact-kind";` and replace `<ChatShellIcon name={kind === "web" ? "web-output" : "ad-canvas"} size={12} />` with `<ChatShellIcon name={isWebsiteKind(kind) ? "web-output" : "ad-canvas"} size={12} />`. (The page switcher stays `kind === "web"`; Task 14 gives sites their own pages UI. The device menu and Share already render for every non-ad kind.)

`apps/frontend/src/features/projects/components/chat-message-reference.tsx`: add `import { isWebsiteKind } from "@/features/chat-shell/model/artifact-kind";` and replace `icon={entity?.icon ?? (reference.kind === "web" ? "web" : undefined)}` with `icon={entity?.icon ?? (isWebsiteKind(reference.kind) ? "web" : undefined)}`.

`apps/frontend/src/features/design-editor/engine/scene/contracts.ts:34`: replace `doc_kind?: "scene" | "web";` with `doc_kind?: "scene" | "web" | "site";`.

- [ ] **Step 9: Share and publish treat a site like a website (Q3 recommendation (a); drop this step if the founder answers (b)).**

`apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.ts`: add `import { isWebsiteKind } from "../model/artifact-kind";` and make these four replacements:
- `const publishable = kind === "web" && Boolean(documentId);` → `const publishable = isWebsiteKind(kind) && Boolean(documentId);`
- `if (kind !== "web") {` → `if (!isWebsiteKind(kind)) {`
- `if (kind === "web") {` → `if (isWebsiteKind(kind)) {`
- `if (kind === "web" && documentId) {` → `if (isWebsiteKind(kind) && documentId) {`

- [ ] **Step 10: The scene loader refuses a site.**

In `apps/frontend/src/features/design-editor/engine/scene/documentStore.ts`, add above `export async function fetchDocument(`:
```ts
/** PLATFORM DELTA (Lane C, master plan Review focus 1): a site document is a Puck
 * site, not a scene. Before Lane A's A1 mapper lands the wire can still call it
 * `ad`; the scene editor must refuse it rather than draw it. */
export const SITE_DOCUMENT_IN_SCENE_EDITOR =
  "This website opens in the website editor, not the ad canvas.";
```
In `fetchDocument`, add `doc_kind?: unknown;` to the `payload` type literal, and insert directly after that `const payload = …;` statement:
```ts
  if (payload.doc_kind === "site") {
    throw new Error(SITE_DOCUMENT_IN_SCENE_EDITOR);
  }
```

- [ ] **Step 11: The stage shows the website pane for a site.**

In `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`:
- add `import { isWebsiteKind } from "../model/artifact-kind";`;
- replace `const veilActive = artifactKind === "web" && nextVeil.active;` with
```tsx
  // The motion is the WEBSITE half only (web or site): the ad lock is not
  // integrated (founder ruling, 2026-09-07), so the ad branch mounts nothing.
  const veilActive = isWebsiteKind(artifactKind) && nextVeil.active;
```
- replace the canvas branch's opening `{artifactKind === "web" ? (` with `{artifactKind !== "ad" ? (`, replace its wrapper's `aria-label={activeDocumentId ? "Web output canvas" : "Empty web output canvas"}` with `aria-label={artifactKind === "web" && activeDocumentId ? "Web output canvas" : "Empty web output canvas"}`, and replace `{activeDocumentId ? (` directly above `<WebArtifactCanvas` with `{artifactKind === "web" && activeDocumentId ? (`.

A site therefore shows the website pane's empty wrapper with the generating veil until Task 8 mounts the editor frame; it can never reach `SceneArtifactCanvas`.

- [ ] **Step 12: Run the new tests and the whole frontend suite.**

Run: `cd apps/frontend && npx tsx --test src/features/chat-shell/model/site-kind.test.ts src/features/design-editor/adapter/gallery-site.test.ts src/features/artifacts/model/artifact-library-site.test.ts src/features/design-editor/engine/scene/document-store-site.test.ts src/features/projects/model/composer-context-catalog-site.test.ts`
Expected: all pass (12 tests).

Run: `cd apps/frontend && npm test 2>&1 | tail -8`
Expected: `# fail 0`. If an existing test pins the exact key set of a mapped gallery/library card, add `documentKind` (the item's own kind) to that expectation — the field is new by design; do not remove it from the mapper.

- [ ] **Step 13: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 14: Commit.**
```bash
git add apps/frontend/src
git commit -m "frontend: site is a kind of its own (Contract 8) — wire enums, documentKind on cards, one kind derivation, surface=site, site dock, scene loader refuses a site"
```

---

### Task 3: C2 — the site repository and the save policy (consumes Contract 2)

The app is the only side that saves (ruling). This task gives it a typed seam for Contract 2 — a Zod-modelled repository with an HTTP adapter through the design BFF (`/api/clue/design/*`) and a fixture adapter with real compare-and-swap — and the web lane's save policy (`features/design-editor/hooks/use-web-manual-edits.ts:83-233`) rewritten for whole-site saves: one save in flight, later edits coalesce into one follow-up save that carries the newest site, the base version tracked in the controller, a 409 says `Document moved on — reloaded.` and reloads, history steps queue behind a save. The policy is a plain class so it can be tested under the repo's DOM-less runner; the hook only mirrors its state.

The Contract 1 schema lives in site-kit (`src/site-document.ts`) because the editor frame parses the same document (Task 4/6).

**Files:**
- Create: `apps/frontend/packages/site-kit/src/site-document.ts`
- Create: `apps/frontend/packages/site-kit/test/site-document.test.ts`
- Modify: `apps/frontend/packages/site-kit/package.json` (`exports`)
- Create: `apps/frontend/src/features/site-editor/model/site-wire.ts`
- Create: `apps/frontend/src/features/site-editor/data/site.repository.ts`
- Create: `apps/frontend/src/features/site-editor/data/site.repository.test.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/site-save-controller.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/site-save-controller.test.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-saves.ts`
- Modify: `apps/frontend/next.config.ts` (`transpilePackages`)
- Modify: `apps/frontend/docs/api-contracts/artifacts.md` (section "Document writes")

**Interfaces:**
- Consumes: Contract 1 (document shape), Contract 2 (routes), assumptions K2, K3, K4, K7.
- Produces:
  - `@clue/site-kit/site-document`: `SITE_ROUTE_PATTERN`, `SiteRouteSchema`, `SHELL_TARGET` (`"shell"`), `SiteTargetSchema`, `type SiteTarget`, `ComponentIdSchema`, `SectionDigestSchema`, `AgentSectionNameSchema`, `SiteComponentSchema`, `SitePageSchema`, `SiteShellSchema`, `SiteDocumentSchema`, `type SiteComponent`, `type SitePage`, `type SiteShell`, `type SiteDocument`, `BrandDataSchema` (output type `BrandData`), `SectionLinkSchema`, `type SectionLink = { name: string; digest: string; token: string; propsSchema: Record<string, unknown> }`.
  - `site-wire.ts`: `SITE_UNDO_CAP = 50`, `LoadedSiteWireSchema`, `type LoadedSite = { documentId: string; title: string; site: SiteDocument; version: number; undoDepth: number; redoDepth: number }`, `SiteWriteResultSchema` → `{ version: number }`, `SiteVersionsWireSchema`, `type SiteVersion = { batchId: string; version: number; actorKind: string; intent: string | null; createdAt: string }`, `SectionLinksWireSchema`, `SiteBrandWireSchema`, `SiteRefusalSchema`.
  - `site.repository.ts`: `class SiteRepositoryError extends Error { code: string; status: number; currentVersion: number | null; errors: readonly string[] }`, `interface SiteRepository { get(documentId): Promise<LoadedSite>; getBrand(documentId): Promise<BrandData>; sectionLinks(documentId): Promise<SectionLink[]>; save(documentId, request: { site: SiteDocument; baseVersion: number; intent?: string }): Promise<{ version: number }>; undo(documentId, baseVersion): Promise<{ version: number }>; redo(documentId, baseVersion): Promise<{ version: number }>; versions(documentId, limit?): Promise<SiteVersion[]>; restore(documentId, batchId, baseVersion): Promise<{ version: number }> }`, `httpSiteRepository(options?: { baseUrl?: string; fetchImpl?: typeof fetch }): SiteRepository`, `fixtureSiteRepository(options?: { site?: SiteDocument; brand?: BrandData }): SiteRepository`, `SITE_FIXTURE_DOCUMENT_ID = "doc_site_fixture"`.
  - `site-save-controller.ts`: `SITE_MOVED_ON_NOTE = "Document moved on — reloaded."`, `SITE_SAVE_FAILED`, `SITE_VERSION_GONE`, `interface SiteSaveState { busy: boolean; note: string | null; error: string | null; baseVersion: number | null; undoDepth: number; redoDepth: number }`, `class SiteSaveController` with `adopt(loaded: { version: number; undoDepth: number; redoDepth: number }): void`, `save(site: SiteDocument, intent?: string): void`, `undo(): void`, `redo(): void`, `restore(batchId: string): void`, `reportError(message: string): void`, `clearMessages(): void`, `dispose(): void`, `get snapshot(): SiteSaveState`.
  - `use-site-saves.ts`: `useSiteSaves(options: { documentId: string | null; repository: SiteRepository; onReload: () => void; lockNote: string }): SiteSaves` where `SiteSaves = SiteSaveState & { save; undo; redo; restore; adopt; reportError; clearMessages }` (same signatures as the controller).

- [ ] **Step 1: Write the failing Contract 1 schema test (site-kit).**

`apps/frontend/packages/site-kit/test/site-document.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BrandDataSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
  SiteTargetSchema,
} from "../src/site-document";
import { garner, site } from "./fixtures/garner";

const stored = site("garner-syracuse");
const document = {
  id: "doc_1",
  title: "Garner × Syracuse",
  theme: {},
  pages: stored.pages,
  shell: stored.shell,
  agent_sections: {},
};

test("the garner fixture site is a Contract 1 site document", () => {
  const parsed = SiteDocumentSchema.parse(document);
  assert.deepEqual(Object.keys(parsed.pages), ["/", "/analysis"]);
});

test("the born-empty site (the Wave 1 minter's shape) parses", () => {
  const parsed = SiteDocumentSchema.parse({
    id: "doc_2",
    title: "New site",
    theme: {},
    pages: { "/": { root: { props: { title: "New site" } }, content: [] } },
    shell: null,
    agent_sections: {},
  });
  assert.equal(parsed.shell, null);
});

test("a site without a home page, with a bad route or an unsafe component id is refused", () => {
  assert.equal(
    SiteDocumentSchema.safeParse({ ...document, pages: { "/analysis": stored.pages["/analysis"] } }).success,
    false,
  );
  assert.equal(
    SiteDocumentSchema.safeParse({ ...document, pages: { ...document.pages, "/Bad Route": stored.pages["/"] } }).success,
    false,
  );
  const page = { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta#1" } }] };
  assert.equal(SiteDocumentSchema.safeParse({ ...document, pages: { "/": page } }).success, false);
});

test("agent sections map PascalCase names to sha256 digests", () => {
  const digest = "a".repeat(64);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { AnalysisSteps: digest } }).success, true);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { analysis: digest } }).success, false);
  assert.equal(SiteDocumentSchema.safeParse({ ...document, agent_sections: { AnalysisSteps: "short" } }).success, false);
});

test("a target is a page route or the shell", () => {
  for (const ok of ["/", "/analysis", "shell"]) assert.equal(SiteTargetSchema.safeParse(ok).success, true, ok);
  for (const bad of ["", "analysis", "/a/b", "SHELL"]) assert.equal(SiteTargetSchema.safeParse(bad).success, false, bad);
});

test("the fixture brand parses and a section link needs a real token", () => {
  assert.equal(BrandDataSchema.parse(garner()).slug, "garner");
  const link = { name: "AnalysisSteps", digest: "b".repeat(64), propsSchema: { type: "object" } };
  assert.equal(SectionLinkSchema.safeParse({ ...link, token: "short" }).success, false);
  assert.equal(SectionLinkSchema.safeParse({ ...link, token: "tok_0123456789abcdef" }).success, true);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd apps/frontend && npx tsx --test packages/site-kit/test/site-document.test.ts`
Expected: FAIL — `Cannot find module '../src/site-document'`.

- [ ] **Step 3: Write the Contract 1 schema.**

`apps/frontend/packages/site-kit/src/site-document.ts`:
```ts
// Contract 1 (Wave 2): the stored site document as a Zod schema that the app and the editor
// frame both parse with. Structural only — routes, ids and shapes — so a malformed document is
// refused at the seam instead of half-rendering. What a page may CONTAIN is the site-kit
// validator's job (validate.ts) and the design API's (Contract 2), never this file's.
import { z } from "zod";
import type { BrandData } from "./brand";

/** "/" or "/<name>", the site-kit route rule (validate.ts). */
export const SITE_ROUTE_PATTERN = /^\/(?:[a-z0-9][a-z0-9-]*)?$/;
export const SiteRouteSchema = z.string().regex(SITE_ROUTE_PATTERN);

/** The shared header and footer are addressed as the "shell" target, never as a page route.
 * That is also what makes an annotation's object id `site:shell#header` (Lane A3). */
export const SHELL_TARGET = "shell" as const;
export const SiteTargetSchema = z.union([SiteRouteSchema, z.literal(SHELL_TARGET)]);
export type SiteTarget = z.infer<typeof SiteTargetSchema>;

/** Unique within its page. Letters, digits, "_" and "-" only, so `site:<route>#<id>.<prop>`
 * can never be ambiguous (plan K5). */
export const ComponentIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,200}$/);
export const SectionDigestSchema = z.string().regex(/^[0-9a-f]{64}$/);
export const AgentSectionNameSchema = z.string().regex(/^[A-Z][A-Za-z0-9]{0,63}$/);

export const SiteComponentSchema = z.looseObject({
  type: z.string().min(1).max(200),
  props: z.looseObject({ id: ComponentIdSchema }),
});

export const SitePageSchema = z.looseObject({
  root: z.looseObject({ props: z.looseObject({ title: z.string().optional() }) }),
  content: z.array(SiteComponentSchema),
  zones: z.record(z.string(), z.unknown()).optional(),
});

export const SiteShellSchema = z.looseObject({
  header: z.record(z.string(), z.unknown()),
  footer: z.record(z.string(), z.unknown()),
});

export const SiteDocumentSchema = z.looseObject({
  id: z.string().min(1),
  title: z.string(),
  theme: z.record(z.string(), z.unknown()).default({}),
  pages: z
    .record(SiteRouteSchema, SitePageSchema)
    .refine((pages) => Object.hasOwn(pages, "/"), { message: "a site always has a home page at /" }),
  shell: SiteShellSchema.nullable(),
  agent_sections: z.record(AgentSectionNameSchema, SectionDigestSchema).default({}),
});

export type SiteComponent = z.infer<typeof SiteComponentSchema>;
export type SitePage = z.infer<typeof SitePageSchema>;
export type SiteShell = z.infer<typeof SiteShellSchema>;
export type SiteDocument = z.infer<typeof SiteDocumentSchema>;

/** BrandData as it travels to the editor frame. Shapes only; the design API builds it. */
export const BrandDataSchema = z
  .looseObject({
    slug: z.string(),
    measured: z.unknown(),
    kit: z.record(z.string(), z.unknown()),
    fonts: z.array(
      z.looseObject({ family: z.string(), weight: z.number().nullable(), style: z.string(), file: z.string() }),
    ),
    assets: z.record(z.string(), z.looseObject({ kind: z.string(), file: z.string() })),
    clones: z.record(
      z.string(),
      z.looseObject({
        id: z.string(),
        label: z.string(),
        html: z.string(),
        css: z.string(),
        slots: z.record(z.string(), z.looseObject({ kind: z.string() })),
      }),
    ),
  })
  .transform((value) => value as unknown as BrandData);

/** Contract 4: one agent section the editor may load, with its short-lived link token. */
export const SectionLinkSchema = z.object({
  name: AgentSectionNameSchema,
  digest: SectionDigestSchema,
  token: z.string().regex(/^[A-Za-z0-9._~-]{16,2048}$/),
  propsSchema: z.record(z.string(), z.unknown()),
});
export type SectionLink = z.infer<typeof SectionLinkSchema>;
```

In `apps/frontend/packages/site-kit/package.json`, add to `"exports"` (after `"./check-section"`):
```json
    "./site-document": "./src/site-document.ts"
```

- [ ] **Step 4: Run the schema test.**

Run: `cd apps/frontend && npx tsx --test packages/site-kit/test/site-document.test.ts && npm test -w @clue/site-kit 2>&1 | tail -4`
Expected: 6 passing in the first run; the package suite ends with `# fail 0`.

- [ ] **Step 5: Write the failing repository and save-policy tests.**

`apps/frontend/src/features/site-editor/data/site.repository.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import {
  SITE_FIXTURE_DOCUMENT_ID,
  SiteRepositoryError,
  fixtureSiteRepository,
  httpSiteRepository,
} from "./site.repository";

const SITE = {
  id: "doc-1",
  title: "Syracuse",
  theme: {},
  pages: { "/": { root: { props: { title: "Home" } }, content: [] } },
  shell: null,
  agent_sections: {},
} as SiteDocument;

function recorder(responses: Response[]) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request");
    return next;
  }) as typeof fetch;
  return { calls, fetchImpl };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("get reads GET /documents/{id} through the design BFF and requires a site", async () => {
  const { calls, fetchImpl } = recorder([
    json({ id: "doc-1", doc_kind: "site", title: "Syracuse", scene: SITE, current_version: 7, undo_stack: [{}, {}], redo_stack: [] }),
  ]);
  const loaded = await httpSiteRepository({ fetchImpl }).get("doc-1");
  assert.equal(calls[0].url, "/api/clue/design/documents/doc-1");
  assert.deepEqual(
    { title: loaded.title, version: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth },
    { title: "Syracuse", version: 7, undoDepth: 2, redoDepth: 0 },
  );
});

test("get refuses a document that is not a site", async () => {
  const { fetchImpl } = recorder([json({ id: "doc-1", doc_kind: "web", title: "W", scene: {}, current_version: 1 })]);
  await assert.rejects(httpSiteRepository({ fetchImpl }).get("doc-1"));
});

test("save PUTs the whole site with base_version and returns the new version", async () => {
  const { calls, fetchImpl } = recorder([json({ document: { id: "doc-1", current_version: 8, doc_kind: "site" } })]);
  const result = await httpSiteRepository({ fetchImpl }).save("doc-1", {
    site: SITE,
    baseVersion: 7,
    intent: "inspector: edit heading",
  });
  assert.equal(calls[0].url, "/api/clue/design/documents/doc-1/site");
  assert.equal(calls[0].init?.method, "PUT");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    site: SITE,
    base_version: 7,
    intent: "inspector: edit heading",
  });
  assert.equal(result.version, 8);
});

test("a 409 base-version refusal surfaces its code and the server's version", async () => {
  const { fetchImpl } = recorder([
    json({ detail: { code: "edits.base_version_mismatch", message: "moved on", current_version: 9 } }, 409),
  ]);
  await assert.rejects(
    httpSiteRepository({ fetchImpl }).save("doc-1", { site: SITE, baseVersion: 7 }),
    (error: unknown) =>
      error instanceof SiteRepositoryError &&
      error.code === "edits.base_version_mismatch" &&
      error.status === 409 &&
      error.currentVersion === 9,
  );
});

test("a 422 refusal carries the validator's errors", async () => {
  const { fetchImpl } = recorder([
    json({ detail: { code: "site.invalid", message: "invalid", errors: ["page.content.0(cta).heading: Too small"] } }, 422),
  ]);
  await assert.rejects(
    httpSiteRepository({ fetchImpl }).save("doc-1", { site: SITE, baseVersion: 7 }),
    (error: unknown) =>
      error instanceof SiteRepositoryError && error.errors[0] === "page.content.0(cta).heading: Too small",
  );
});

test("undo, redo, versions, restore, section links and brand use their routes", async () => {
  const { calls, fetchImpl } = recorder([
    json({ document: { id: "doc-1", current_version: 8 }, undone_batch_id: "b1" }),
    json({ document: { id: "doc-1", current_version: 9 }, redone_batch_id: "b1" }),
    json({ versions: [{ batch_id: "b2", version: 9, actor_kind: "human", intent: null, created_at: "2026-10-11T10:00:00Z" }] }),
    json({ document: { id: "doc-1", current_version: 10 } }),
    json({
      links: [
        {
          name: "AnalysisSteps",
          digest: "c".repeat(64),
          token: "tok_0123456789abcdef",
          expires_at: "2026-10-11T10:10:00Z",
          props_schema: { type: "object" },
        },
      ],
    }),
    json({ brand: { slug: "garner", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } }),
  ]);
  const repository = httpSiteRepository({ fetchImpl });
  assert.equal((await repository.undo("doc-1", 7)).version, 8);
  assert.equal((await repository.redo("doc-1", 8)).version, 9);
  assert.deepEqual(await repository.versions("doc-1", 20), [
    { batchId: "b2", version: 9, actorKind: "human", intent: null, createdAt: "2026-10-11T10:00:00Z" },
  ]);
  assert.equal((await repository.restore("doc-1", "b2", 9)).version, 10);
  assert.deepEqual((await repository.sectionLinks("doc-1"))[0].propsSchema, { type: "object" });
  assert.equal((await repository.getBrand("doc-1")).slug, "garner");
  const base = "/api/clue/design/documents/doc-1";
  assert.deepEqual(
    calls.map((call) => [call.init?.method ?? "GET", call.url]),
    [
      ["POST", `${base}/site/undo`],
      ["POST", `${base}/site/redo`],
      ["GET", `${base}/site/versions?limit=20`],
      ["POST", `${base}/site/versions/b2/restore`],
      ["POST", `${base}/site/section-links`],
      ["GET", `${base}/site/brand`],
    ],
  );
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { base_version: 7 });
});

test("the fixture enforces compare-and-swap and keeps an undo stack", async () => {
  const repository = fixtureSiteRepository();
  const loaded = await repository.get(SITE_FIXTURE_DOCUMENT_ID);
  const saved = await repository.save(SITE_FIXTURE_DOCUMENT_ID, { site: loaded.site, baseVersion: loaded.version });
  assert.equal(saved.version, loaded.version + 1);
  await assert.rejects(
    repository.save(SITE_FIXTURE_DOCUMENT_ID, { site: loaded.site, baseVersion: loaded.version }),
    (error: unknown) => error instanceof SiteRepositoryError && error.code === "edits.base_version_mismatch",
  );
  const undone = await repository.undo(SITE_FIXTURE_DOCUMENT_ID, saved.version);
  assert.equal(undone.version, saved.version + 1);
  await assert.rejects(
    repository.undo(SITE_FIXTURE_DOCUMENT_ID, undone.version),
    (error: unknown) => error instanceof SiteRepositoryError && error.code === "undo.empty",
  );
});
```

`apps/frontend/src/features/site-editor/hooks/site-save-controller.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { SiteRepositoryError, type SiteRepository } from "../data/site.repository";
import {
  SITE_MOVED_ON_NOTE,
  SITE_VERSION_GONE,
  SiteSaveController,
  type SiteSaveState,
} from "./site-save-controller";

const LOCK = "The lock's own sentence.";

function site(heading: string): SiteDocument {
  return {
    id: "doc-1",
    title: "S",
    theme: {},
    pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta", heading } }] } },
    shell: null,
    agent_sections: {},
  } as SiteDocument;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function harness({ adopt = true } = {}) {
  const calls: { op: string; base: number; heading?: string; batchId?: string }[] = [];
  const pending: ReturnType<typeof deferred<{ version: number }>>[] = [];
  const next = () => {
    const result = deferred<{ version: number }>();
    pending.push(result);
    return result.promise;
  };
  const headingOf = (value: SiteDocument) =>
    String((value.pages["/"].content[0].props as { heading: string }).heading);
  const repository: Pick<SiteRepository, "save" | "undo" | "redo" | "restore"> = {
    save: (_id, request) => {
      calls.push({ op: "save", base: request.baseVersion, heading: headingOf(request.site) });
      return next();
    },
    undo: (_id, base) => {
      calls.push({ op: "undo", base });
      return next();
    },
    redo: (_id, base) => {
      calls.push({ op: "redo", base });
      return next();
    },
    restore: (_id, batchId, base) => {
      calls.push({ op: "restore", base, batchId });
      return next();
    },
  };
  const states: SiteSaveState[] = [];
  let reloads = 0;
  const controller = new SiteSaveController({
    documentId: "doc-1",
    lockNote: LOCK,
    onReload: () => {
      reloads += 1;
    },
    onState: (state) => states.push(state),
    repository,
  });
  if (adopt) controller.adopt({ version: 5, undoDepth: 0, redoDepth: 0 });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  return { calls, controller, pending, reloads: () => reloads, settle, states };
}

test("one save in flight; later edits coalesce into one follow-up save of the newest site", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  h.controller.save(site("c"));
  assert.deepEqual(h.calls, [{ op: "save", base: 5, heading: "a" }]);
  h.pending[0].resolve({ version: 6 });
  await h.settle();
  assert.deepEqual(h.calls.map((call) => [call.op, call.base, call.heading]), [
    ["save", 5, "a"],
    ["save", 6, "c"],
  ]);
  h.pending[1].resolve({ version: 7 });
  await h.settle();
  assert.equal(h.controller.snapshot.baseVersion, 7);
  assert.equal(h.controller.snapshot.undoDepth, 2);
  assert.equal(h.controller.snapshot.busy, false);
  assert.equal(h.reloads(), 0, "a successful save does not reload the canvas");
});

test("a base-version refusal says the document moved on, drops queued edits and reloads", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  h.pending[0].reject(
    new SiteRepositoryError("moved", { code: "edits.base_version_mismatch", status: 409, currentVersion: 9 }),
  );
  await h.settle();
  assert.equal(h.controller.snapshot.note, SITE_MOVED_ON_NOTE);
  assert.equal(h.reloads(), 1);
  assert.equal(h.calls.length, 1, "the queued edit is dropped with the refused one");
});

test("a refusal because the agent is running carries the lock's own words", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.pending[0].reject(new SiteRepositoryError("busy", { code: "document.agent_run_active", status: 409 }));
  await h.settle();
  assert.equal(h.controller.snapshot.note, LOCK);
  assert.equal(h.reloads(), 1);
});

test("a validation refusal shows the first error and reloads the saved state", async () => {
  const h = harness();
  h.controller.save(site(""));
  h.pending[0].reject(
    new SiteRepositoryError("invalid", { code: "site.invalid", status: 422, errors: ["page.content.0(cta).heading: Too small"] }),
  );
  await h.settle();
  assert.equal(h.controller.snapshot.error, "page.content.0(cta).heading: Too small");
  assert.equal(h.controller.snapshot.note, null);
  assert.equal(h.reloads(), 1);
});

test("a transport failure keeps the edit for the next save and does not reload", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.pending[0].reject(new TypeError("Failed to fetch"));
  await h.settle();
  assert.equal(h.controller.snapshot.error, "Failed to fetch");
  assert.equal(h.reloads(), 0);
  h.controller.save(site("b"));
  assert.deepEqual(h.calls.at(-1), { op: "save", base: 5, heading: "b" });
});

test("undo waits behind an in-flight save, then steps the server stack and reloads", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.undo();
  assert.deepEqual(h.calls.map((call) => call.op), ["save"]);
  h.pending[0].resolve({ version: 6 });
  await h.settle();
  assert.deepEqual(h.calls.map((call) => [call.op, call.base]), [
    ["save", 5],
    ["undo", 6],
  ]);
  h.pending[1].resolve({ version: 7 });
  await h.settle();
  assert.equal(h.reloads(), 1);
  assert.equal(h.controller.snapshot.undoDepth, 0);
  assert.equal(h.controller.snapshot.redoDepth, 1);
});

test("an empty stack resyncs quietly", async () => {
  const h = harness();
  h.controller.undo();
  h.pending[0].reject(new SiteRepositoryError("empty", { code: "undo.empty", status: 409 }));
  await h.settle();
  assert.equal(h.reloads(), 1);
  assert.equal(h.controller.snapshot.note, null);
  assert.equal(h.controller.snapshot.error, null);
});

test("restoring a version that is gone says so and reloads", async () => {
  const h = harness();
  h.controller.restore("batch_9");
  assert.deepEqual(h.calls, [{ op: "restore", base: 5, batchId: "batch_9" }]);
  h.pending[0].reject(new SiteRepositoryError("gone", { code: "version.not_found", status: 404 }));
  await h.settle();
  assert.equal(h.controller.snapshot.error, SITE_VERSION_GONE);
  assert.equal(h.reloads(), 1);
});

test("nothing is sent before a document version is adopted", () => {
  const h = harness({ adopt: false });
  h.controller.save(site("a"));
  h.controller.undo();
  assert.deepEqual(h.calls, []);
});
```

- [ ] **Step 6: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/data/site.repository.test.ts src/features/site-editor/hooks/site-save-controller.test.ts`
Expected: FAIL — `Cannot find module './site.repository'`.

- [ ] **Step 7: Write the wire schemas.**

`apps/frontend/src/features/site-editor/model/site-wire.ts`:
```ts
import { z } from "zod";
import {
  AgentSectionNameSchema,
  BrandDataSchema,
  SectionDigestSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
} from "@clue/site-kit/site-document";

/** Contract 2: one save is one undo step, one agent turn is one undo step, cap 50. */
export const SITE_UNDO_CAP = 50;

/** `GET /documents/{id}` for a site (plan assumption K4). Anything but `doc_kind: "site"` is
 * refused here, so a site seam can never be handed a scene or a WebDoc. */
export const LoadedSiteWireSchema = z
  .object({
    id: z.string().min(1),
    doc_kind: z.literal("site"),
    title: z.string(),
    scene: SiteDocumentSchema,
    current_version: z.number().int().nonnegative(),
    undo_stack: z.array(z.unknown()).optional(),
    redo_stack: z.array(z.unknown()).optional(),
  })
  .transform((wire) => ({
    documentId: wire.id,
    title: wire.title,
    site: wire.scene,
    version: wire.current_version,
    undoDepth: wire.undo_stack?.length ?? 0,
    redoDepth: wire.redo_stack?.length ?? 0,
  }));
export type LoadedSite = z.output<typeof LoadedSiteWireSchema>;

/** Plan assumption K3: `GET /documents/{id}/site/brand`. */
export const SiteBrandWireSchema = z.object({ brand: BrandDataSchema }).transform((wire) => wire.brand);

/** Contract 4 + plan assumption K2: `POST /documents/{id}/site/section-links`. */
export const SectionLinksWireSchema = z
  .object({
    links: z.array(
      z.object({
        name: AgentSectionNameSchema,
        digest: SectionDigestSchema,
        token: z.string(),
        expires_at: z.string(),
        props_schema: z.record(z.string(), z.unknown()),
      }),
    ),
  })
  .transform((wire) =>
    wire.links.map((link) =>
      SectionLinkSchema.parse({ name: link.name, digest: link.digest, token: link.token, propsSchema: link.props_schema }),
    ),
  );

/** Every Contract 2 write answers with the document's new version. */
export const SiteWriteResultSchema = z
  .object({ document: z.object({ id: z.string().min(1), current_version: z.number().int().nonnegative() }) })
  .transform((wire) => ({ version: wire.document.current_version }));
export type SiteWriteResult = z.output<typeof SiteWriteResultSchema>;

export const SiteVersionsWireSchema = z
  .object({
    versions: z.array(
      z.object({
        batch_id: z.string().min(1),
        version: z.number().int().nonnegative(),
        actor_kind: z.string().min(1),
        intent: z.string().nullable().optional(),
        created_at: z.string().min(1),
      }),
    ),
  })
  .transform((wire) =>
    wire.versions.map((version) => ({
      batchId: version.batch_id,
      version: version.version,
      actorKind: version.actor_kind,
      intent: version.intent ?? null,
      createdAt: version.created_at,
    })),
  );
export type SiteVersion = z.output<typeof SiteVersionsWireSchema>[number];

/** The design API's refusal body: FastAPI `detail`, an object or a bare string. */
export const SiteRefusalSchema = z.object({
  detail: z.union([
    z.string(),
    z.looseObject({
      code: z.string().optional(),
      message: z.string().optional(),
      current_version: z.number().int().optional(),
      errors: z.array(z.string()).optional(),
    }),
  ]),
});
```

- [ ] **Step 8: Write the repository.**

`apps/frontend/src/features/site-editor/data/site.repository.ts`:
```ts
import type { BrandData } from "@clue/site-kit";
import { SiteDocumentSchema, type SectionLink, type SiteDocument } from "@clue/site-kit/site-document";
import { DESIGN_API_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import {
  LoadedSiteWireSchema,
  SITE_UNDO_CAP,
  SectionLinksWireSchema,
  SiteBrandWireSchema,
  SiteRefusalSchema,
  SiteVersionsWireSchema,
  SiteWriteResultSchema,
  type LoadedSite,
  type SiteVersion,
  type SiteWriteResult,
} from "../model/site-wire";

/** A typed refusal from the site seam: the design API's code, the HTTP status, and on a CAS
 * conflict the server's version; on a 422 the validator's messages. */
export class SiteRepositoryError extends Error {
  readonly code: string;
  readonly status: number;
  readonly currentVersion: number | null;
  readonly errors: readonly string[];

  constructor(
    message: string,
    options: { code: string; status: number; currentVersion?: number | null; errors?: readonly string[] },
  ) {
    super(message);
    this.name = "SiteRepositoryError";
    this.code = options.code;
    this.status = options.status;
    this.currentVersion = options.currentVersion ?? null;
    this.errors = options.errors ?? [];
  }
}

export interface SiteSaveRequest {
  site: SiteDocument;
  baseVersion: number;
  intent?: string;
}

/** Contract 2 (writes, undo, versions) + K3/K4 (reads) + Contract 4 (section links). */
export interface SiteRepository {
  get(documentId: string): Promise<LoadedSite>;
  getBrand(documentId: string): Promise<BrandData>;
  sectionLinks(documentId: string): Promise<SectionLink[]>;
  save(documentId: string, request: SiteSaveRequest): Promise<SiteWriteResult>;
  undo(documentId: string, baseVersion: number): Promise<SiteWriteResult>;
  redo(documentId: string, baseVersion: number): Promise<SiteWriteResult>;
  versions(documentId: string, limit?: number): Promise<SiteVersion[]>;
  restore(documentId: string, batchId: string, baseVersion: number): Promise<SiteWriteResult>;
}

async function refusalOf(response: Response): Promise<SiteRepositoryError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON refusal keeps the status-shaped message below.
  }
  const parsed = SiteRefusalSchema.safeParse(body);
  const detail = parsed.success ? parsed.data.detail : null;
  if (typeof detail === "string") {
    return new SiteRepositoryError(detail, { code: "site.request_failed", status: response.status });
  }
  return new SiteRepositoryError(detail?.message ?? `Website request failed (HTTP ${response.status}).`, {
    code: detail?.code ?? "site.request_failed",
    currentVersion: detail?.current_version ?? null,
    errors: detail?.errors ?? [],
    status: response.status,
  });
}

/** Browser adapter: every call goes through the same-origin design BFF, which proves the
 * session and stamps the workspace header server-side (`app/api/clue/design/[...path]`). */
export function httpSiteRepository({
  baseUrl = DESIGN_API_BFF_PREFIX,
  fetchImpl,
}: { baseUrl?: string; fetchImpl?: typeof fetch } = {}): SiteRepository {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const call = async (path: string, init?: RequestInit): Promise<unknown> => {
    const response = await doFetch(`${baseUrl}${path}`, { cache: "no-store", ...init });
    if (!response.ok) throw await refusalOf(response);
    return response.json();
  };
  const post = (body: unknown, method = "POST"): RequestInit => ({
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method,
  });
  const documentPath = (documentId: string) => `/documents/${encodeURIComponent(documentId)}`;
  return {
    async get(documentId) {
      return LoadedSiteWireSchema.parse(await call(documentPath(documentId)));
    },
    async getBrand(documentId) {
      return SiteBrandWireSchema.parse(await call(`${documentPath(documentId)}/site/brand`));
    },
    async sectionLinks(documentId) {
      return SectionLinksWireSchema.parse(await call(`${documentPath(documentId)}/site/section-links`, post({})));
    },
    async save(documentId, { site, baseVersion, intent }) {
      const body = { site, base_version: baseVersion, ...(intent ? { intent } : {}) };
      return SiteWriteResultSchema.parse(await call(`${documentPath(documentId)}/site`, post(body, "PUT")));
    },
    async undo(documentId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(`${documentPath(documentId)}/site/undo`, post({ base_version: baseVersion })),
      );
    },
    async redo(documentId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(`${documentPath(documentId)}/site/redo`, post({ base_version: baseVersion })),
      );
    },
    async versions(documentId, limit = 50) {
      return SiteVersionsWireSchema.parse(await call(`${documentPath(documentId)}/site/versions?limit=${limit}`));
    },
    async restore(documentId, batchId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(
          `${documentPath(documentId)}/site/versions/${encodeURIComponent(batchId)}/restore`,
          post({ base_version: baseVersion }),
        ),
      );
    },
  };
}

export const SITE_FIXTURE_DOCUMENT_ID = "doc_site_fixture";

const FIXTURE_BRAND = {
  slug: "fixture",
  measured: null,
  kit: { tokens: {} },
  fonts: [],
  assets: {},
  clones: {},
} as unknown as BrandData;

const FIXTURE_SITE: SiteDocument = SiteDocumentSchema.parse({
  id: SITE_FIXTURE_DOCUMENT_ID,
  title: "Fixture site",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Home" } },
      content: [
        {
          type: "CtaBand",
          props: { id: "cta", surface: "brand", heading: "The one next step", body: "", buttonLabel: "Get started", buttonHref: "" },
        },
      ],
    },
  },
  shell: null,
  agent_sections: {},
});

/** In-memory adapter with the real compare-and-swap and stack rules, for local design work
 * and tests. Never a fallback: nothing selects it implicitly. */
export function fixtureSiteRepository({
  brand = FIXTURE_BRAND,
  site = FIXTURE_SITE,
}: { brand?: BrandData; site?: SiteDocument } = {}): SiteRepository {
  type HistoryRow = SiteVersion & { site: SiteDocument };
  let version = 1;
  let batch = 1;
  let current = site;
  const undoStack: SiteDocument[] = [];
  const redoStack: SiteDocument[] = [];
  const history: HistoryRow[] = [
    { batchId: "batch_1", version: 1, actorKind: "agent", intent: null, createdAt: "2026-10-11T09:01:00.000Z", site },
  ];
  const known = (documentId: string) => {
    if (documentId !== site.id) {
      throw new SiteRepositoryError("No such website.", { code: "document.not_found", status: 404 });
    }
  };
  const compareAndSwap = (baseVersion: number) => {
    if (baseVersion !== version) {
      throw new SiteRepositoryError("The document moved on.", {
        code: "edits.base_version_mismatch",
        currentVersion: version,
        status: 409,
      });
    }
  };
  const commit = (next: SiteDocument, intent: string | null): SiteWriteResult => {
    batch += 1;
    version += 1;
    current = next;
    history.unshift({
      batchId: `batch_${batch}`,
      version,
      actorKind: "human",
      intent,
      createdAt: new Date(Date.UTC(2026, 9, 11, 9, batch)).toISOString(),
      site: next,
    });
    return { version };
  };
  const pushUndo = (snapshot: SiteDocument) => {
    undoStack.push(snapshot);
    if (undoStack.length > SITE_UNDO_CAP) undoStack.shift();
  };
  return {
    async get(documentId) {
      known(documentId);
      return { documentId, title: current.title, site: current, version, undoDepth: undoStack.length, redoDepth: redoStack.length };
    },
    async getBrand(documentId) {
      known(documentId);
      return brand;
    },
    async sectionLinks(documentId) {
      known(documentId);
      return [];
    },
    async save(documentId, request) {
      known(documentId);
      compareAndSwap(request.baseVersion);
      pushUndo(current);
      redoStack.length = 0;
      return commit(request.site, request.intent ?? null);
    },
    async undo(documentId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const previous = undoStack.pop();
      if (!previous) throw new SiteRepositoryError("Nothing to undo.", { code: "undo.empty", status: 409 });
      redoStack.push(current);
      return commit(previous, "undo");
    },
    async redo(documentId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const next = redoStack.pop();
      if (!next) throw new SiteRepositoryError("Nothing to redo.", { code: "redo.empty", status: 409 });
      pushUndo(current);
      return commit(next, "redo");
    },
    async versions(documentId, limit = 50) {
      known(documentId);
      return history.slice(0, limit).map((row) => ({
        batchId: row.batchId,
        version: row.version,
        actorKind: row.actorKind,
        intent: row.intent,
        createdAt: row.createdAt,
      }));
    },
    async restore(documentId, batchId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const target = history.find((row) => row.batchId === batchId);
      if (!target) throw new SiteRepositoryError("No such version.", { code: "version.not_found", status: 404 });
      pushUndo(current);
      redoStack.length = 0;
      return commit(target.site, "restore");
    },
  };
}
```

- [ ] **Step 9: Write the save controller.**

`apps/frontend/src/features/site-editor/hooks/site-save-controller.ts`:
```ts
import type { SiteDocument } from "@clue/site-kit/site-document";
import { SiteRepositoryError, type SiteRepository } from "../data/site.repository";
import { SITE_UNDO_CAP } from "../model/site-wire";

/**
 * Lane C / C2: the site lane's save policy, the web lane's (`use-web-manual-edits.ts`) for
 * whole-site saves. A plain class so it is testable without a DOM; `useSiteSaves` mirrors
 * its state into React.
 *
 *  - One request in flight. Later edits coalesce: only the NEWEST site is saved next, because
 *    every save carries the whole site, so the newest one already contains the others.
 *  - Undo / redo / restore queue behind a pending save (latest step wins).
 *  - 409 `edits.base_version_mismatch` → the web lane's exact note, the edit is dropped, reload.
 *  - 409 `document.agent_run_active` → the agent-run lock's own sentence, reload.
 *  - 422 → the validator's first message, reload (the canvas goes back to what is saved).
 *  - A transport failure keeps the edit: the next save carries the whole site again.
 *  - A history step reloads on success (the frame must show the stepped document); a save does
 *    not (the frame already shows what was saved).
 */
export const SITE_MOVED_ON_NOTE = "Document moved on — reloaded.";
export const SITE_SAVE_FAILED = "This edit could not be saved.";
export const SITE_VERSION_GONE = "That version is no longer available.";

export interface SiteSaveState {
  busy: boolean;
  note: string | null;
  error: string | null;
  baseVersion: number | null;
  undoDepth: number;
  redoDepth: number;
}

export const IDLE_SITE_SAVE_STATE: SiteSaveState = {
  busy: false,
  note: null,
  error: null,
  baseVersion: null,
  undoDepth: 0,
  redoDepth: 0,
};

type HistoryStep = { kind: "undo" } | { kind: "redo" } | { kind: "restore"; batchId: string };

export interface SiteSaveControllerDeps {
  documentId: string;
  lockNote: string;
  onReload: () => void;
  onState: (state: SiteSaveState) => void;
  repository: Pick<SiteRepository, "save" | "undo" | "redo" | "restore">;
}

export class SiteSaveController {
  private state: SiteSaveState = IDLE_SITE_SAVE_STATE;
  private inFlight = false;
  private pendingSave: { site: SiteDocument; intent?: string } | null = null;
  private pendingStep: HistoryStep | null = null;
  private disposed = false;

  constructor(private readonly deps: SiteSaveControllerDeps) {}

  get snapshot(): SiteSaveState {
    return this.state;
  }

  /** The version and stacks of the document as just loaded (first load and every reload). */
  adopt(loaded: { version: number; undoDepth: number; redoDepth: number }): void {
    this.update({ baseVersion: loaded.version, undoDepth: loaded.undoDepth, redoDepth: loaded.redoDepth });
  }

  save(site: SiteDocument, intent?: string): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      this.pendingSave = { site, intent };
      return;
    }
    void this.runSave(site, intent);
  }

  undo(): void {
    this.step({ kind: "undo" });
  }

  redo(): void {
    this.step({ kind: "redo" });
  }

  restore(batchId: string): void {
    this.step({ kind: "restore", batchId });
  }

  /** The inline error line, for adjacent write paths that fail before any save (an upload). */
  reportError(message: string): void {
    this.update({ note: null, error: message });
  }

  clearMessages(): void {
    this.update({ note: null, error: null });
  }

  dispose(): void {
    this.disposed = true;
  }

  private step(step: HistoryStep): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight || this.pendingSave) {
      this.pendingStep = step;
      return;
    }
    void this.runStep(step);
  }

  private async runSave(site: SiteDocument, intent?: string): Promise<void> {
    const baseVersion = this.state.baseVersion;
    if (baseVersion === null) return;
    this.begin();
    try {
      const result = await this.deps.repository.save(this.deps.documentId, { site, baseVersion, intent });
      this.update({
        baseVersion: result.version,
        undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP),
        redoDepth: 0,
      });
      this.finish();
    } catch (cause) {
      this.abandon();
      this.refused(cause, "save");
    }
  }

  private async runStep(step: HistoryStep): Promise<void> {
    const baseVersion = this.state.baseVersion;
    if (baseVersion === null) return;
    this.begin();
    try {
      const { repository, documentId } = this.deps;
      const result =
        step.kind === "undo"
          ? await repository.undo(documentId, baseVersion)
          : step.kind === "redo"
            ? await repository.redo(documentId, baseVersion)
            : await repository.restore(documentId, step.batchId, baseVersion);
      const depths =
        step.kind === "undo"
          ? { undoDepth: Math.max(this.state.undoDepth - 1, 0), redoDepth: this.state.redoDepth + 1 }
          : step.kind === "redo"
            ? { undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP), redoDepth: Math.max(this.state.redoDepth - 1, 0) }
            : { undoDepth: Math.min(this.state.undoDepth + 1, SITE_UNDO_CAP), redoDepth: 0 };
      this.update({ baseVersion: result.version, ...depths });
      this.finish();
      this.deps.onReload();
    } catch (cause) {
      this.abandon();
      this.refused(cause, step.kind);
    }
  }

  private begin(): void {
    this.inFlight = true;
    this.update({ busy: true, note: null, error: null });
  }

  private finish(): void {
    this.inFlight = false;
    if (this.pendingSave) {
      const next = this.pendingSave;
      this.pendingSave = null;
      void this.runSave(next.site, next.intent);
      return;
    }
    if (this.pendingStep) {
      const next = this.pendingStep;
      this.pendingStep = null;
      void this.runStep(next);
      return;
    }
    this.update({ busy: false });
  }

  private abandon(): void {
    this.inFlight = false;
    this.pendingSave = null;
    this.pendingStep = null;
  }

  private refused(cause: unknown, operation: "save" | HistoryStep["kind"]): void {
    const error = cause instanceof SiteRepositoryError ? cause : null;
    if (error?.status === 409 && (error.code === "undo.empty" || error.code === "redo.empty")) {
      this.update({ busy: false });
      this.deps.onReload();
      return;
    }
    if (error?.status === 409 && error.code === "edits.base_version_mismatch") {
      this.update({ busy: false, note: SITE_MOVED_ON_NOTE, error: null });
      this.deps.onReload();
      return;
    }
    if (error?.status === 409 && error.code === "document.agent_run_active") {
      this.update({ busy: false, note: this.deps.lockNote, error: null });
      this.deps.onReload();
      return;
    }
    if (error?.status === 422) {
      this.update({ busy: false, note: null, error: error.errors[0] ?? error.message });
      this.deps.onReload();
      return;
    }
    if (error?.status === 404 && operation === "restore") {
      this.update({ busy: false, note: null, error: SITE_VERSION_GONE });
      this.deps.onReload();
      return;
    }
    this.update({ busy: false, note: null, error: cause instanceof Error ? cause.message : SITE_SAVE_FAILED });
  }

  private update(patch: Partial<SiteSaveState>): void {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.deps.onState(this.state);
  }
}
```

- [ ] **Step 10: Write the hook.**

`apps/frontend/src/features/site-editor/hooks/use-site-saves.ts`:
```ts
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { SiteRepository } from "../data/site.repository";
import { IDLE_SITE_SAVE_STATE, SiteSaveController, type SiteSaveState } from "./site-save-controller";

export interface SiteSaves extends SiteSaveState {
  save: (site: SiteDocument, intent?: string) => void;
  undo: () => void;
  redo: () => void;
  restore: (batchId: string) => void;
  adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => void;
  reportError: (message: string) => void;
  clearMessages: () => void;
}

/** One controller per open site document; its state mirrored for rendering. */
export function useSiteSaves({
  documentId,
  lockNote,
  onReload,
  repository,
}: {
  documentId: string | null;
  lockNote: string;
  onReload: () => void;
  repository: SiteRepository;
}): SiteSaves {
  // Latest-value ref, written in a passive effect (this repo's react-hooks rule).
  const onReloadRef = useRef(onReload);
  useEffect(() => {
    onReloadRef.current = onReload;
  });
  const [state, setState] = useState<SiteSaveState>(IDLE_SITE_SAVE_STATE);
  const controller = useMemo(
    () =>
      documentId
        ? new SiteSaveController({ documentId, lockNote, onReload: () => onReloadRef.current(), onState: setState, repository })
        : null,
    [documentId, lockNote, repository],
  );
  useEffect(() => () => controller?.dispose(), [controller]);
  // A new document starts from an idle state: React's adjust-state-on-prop-change pattern
  // (render-time comparison), never a setState inside an effect.
  const [owner, setOwner] = useState(controller);
  if (owner !== controller) {
    setOwner(controller);
    setState(IDLE_SITE_SAVE_STATE);
  }
  const actions = useMemo(
    () => ({
      adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => controller?.adopt(loaded),
      clearMessages: () => controller?.clearMessages(),
      redo: () => controller?.redo(),
      reportError: (message: string) => controller?.reportError(message),
      restore: (batchId: string) => controller?.restore(batchId),
      save: (site: SiteDocument, intent?: string) => controller?.save(site, intent),
      undo: () => controller?.undo(),
    }),
    [controller],
  );
  return { ...state, ...actions };
}
```

- [ ] **Step 11: Let Next compile the site-kit sources the app now imports.**

In `apps/frontend/next.config.ts`, add inside `nextConfig` (directly after `output: "standalone",`):
```ts
  // Lane C: the app imports TypeScript sources from the @clue/site-kit workspace package
  // (site-document, editor-protocol, editor-site, editor-origin), so Next must compile them.
  transpilePackages: ["@clue/site-kit"],
```

- [ ] **Step 12: Run the tests.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/data/site.repository.test.ts src/features/site-editor/hooks/site-save-controller.test.ts`
Expected: 16 passing, 0 failing.

- [ ] **Step 13: Record the contract in the frontend's contract doc.**

In `apps/frontend/docs/api-contracts/artifacts.md`, append to the end of the section `## Document writes (design API through /api/clue/design)`:
```markdown

### Site documents (Wave 2 Contract 2; read by `src/features/site-editor/data/site.repository.ts`)

- `GET /documents/{id}` → for `doc_kind: "site"`: `{ id, doc_kind: "site", title, scene: <Contract 1 site>, current_version, undo_stack: [], redo_stack: [] }` (plan K4; anything but `site` is refused by the seam).
- `PUT /documents/{id}/site` body `{ site, base_version, intent? }` → `{ document: { id, current_version, doc_kind: "site" } }`. Refusals: 409 `edits.base_version_mismatch` (+ `current_version`), 422 `site.invalid` (+ `errors[]`), 409 `document.agent_run_active`, 409 `document.kind_unsupported`.
- `POST /documents/{id}/site/undo` · `/redo` body `{ base_version }` → `{ document, undone_batch_id | redone_batch_id }`; 409 `undo.empty` · `redo.empty`.
- `GET /documents/{id}/site/versions?limit=` → `{ versions: [{ batch_id, version, actor_kind, intent, created_at }] }`, newest first.
- `POST /documents/{id}/site/versions/{batch_id}/restore` body `{ base_version }` → `{ document }`; 404 `version.not_found`. The restore is itself an undoable write.
- `POST /documents/{id}/site/section-links` → `{ links: [{ name, digest, token, expires_at, props_schema }] }` (Contract 4 + plan K2).
- `GET /documents/{id}/site/brand` → `{ brand: BrandData }` (plan K3, proposed).
- Refusal bodies are FastAPI `{ detail: { code, message, current_version?, errors? } }` or `{ detail: "<string>" }`.
- Save policy (frontend): one request in flight, edits coalesce into the newest site, a 409 shows "Document moved on — reloaded." and reloads; the app is the only side that saves.
```

- [ ] **Step 14: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 15: Commit.**
```bash
git add apps/frontend/packages/site-kit/src/site-document.ts apps/frontend/packages/site-kit/test/site-document.test.ts apps/frontend/packages/site-kit/package.json apps/frontend/src/features/site-editor apps/frontend/next.config.ts apps/frontend/docs/api-contracts/artifacts.md
git commit -m "site editor: Contract 1 schema in site-kit, the site repository (BFF + CAS fixture) and the web lane's save policy for whole-site saves"
```

---

### Task 4: C3a — the editor protocol, shared site edits and the editor origin (Contract 6, Contract 9 helpers)

Both sides of the frame boundary need the same message schemas, the same acceptance rules and the same edit functions, so they live once in site-kit as pure modules (no Puck, no DOM, no `node-html-parser` imports — the app bundles them):

- `editor-protocol.ts` — Contract 6 messages as Zod, typed builders, and the two acceptors (`acceptFrameMessage` for the app, `acceptAppMessage` for the frame) that check origin, source, nonce and document id on every message.
- `editor-site.ts` — the edits both sides make (`withComponentProps`, `withAssetAt`, `withPage`, path helpers, `canonicalJson`, `internalRoute`, `shortcutFor`), so the app (which saves) and the frame (which renders) can never disagree on what an edit did.
- `editor-origin.ts` — the opaque per-workspace label (`sha256("clue-site-editor-label:v1:" + workspaceId)`, first 32 hex characters), the origin built from it, and the reverse lookup from a `Host` header (Contract 9).

**Files:**
- Create: `apps/frontend/packages/site-kit/src/editor-protocol.ts`
- Create: `apps/frontend/packages/site-kit/src/editor-site.ts`
- Create: `apps/frontend/packages/site-kit/src/editor-origin.ts`
- Create: `apps/frontend/packages/site-kit/test/editor-protocol.test.ts`
- Create: `apps/frontend/packages/site-kit/test/editor-site.test.ts`
- Create: `apps/frontend/packages/site-kit/test/editor-origin.test.ts`
- Modify: `apps/frontend/packages/site-kit/package.json` (`exports`)
- Modify: `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` (Contract 6 refinements, plan K6)
- Create: `apps/frontend/docs/architecture/site-editor.md`
- Modify: `apps/frontend/docs/README.md` (canonical documents index)

**Interfaces:**
- Consumes: `@clue/site-kit/site-document` from Task 3 (`SiteDocumentSchema`, `BrandDataSchema`, `SectionLinkSchema`, `SiteRouteSchema`, `SiteTargetSchema`, `ComponentIdSchema`, `SHELL_TARGET`, `type SiteDocument`, `type SitePage`, `type SiteTarget`).
- Produces:
  - `@clue/site-kit/editor-protocol`: `EDITOR_CHANNEL = "clue-site-editor"`, `EDITOR_PROTOCOL_VERSION = 1`, `EditorModeSchema` / `type EditorMode = "edit" | "preview"`, `PreviewDeviceSchema` / `type PreviewDevice = "Desktop" | "Tablet" | "Mobile"`, `PropPathSchema`, `AssetStoreUrlSchema`, `GeometrySchema` / `type SiteGeometry = { viewport: Rect; document: Rect }` (Rect = `{x, y, top, right, bottom, left, width, height}`, the web bridge's `WebNodeRect`), `type FieldKind`, `type FieldDescription = { name: string; label: string; kind: FieldKind; options?: { label: string; value: string | number | boolean }[]; item?: FieldDescription[] }`, `FieldDescriptionSchema`, `AppToFrameMessageSchema`, `FrameToAppMessageSchema`, `type AppToFrameMessage`, `type FrameToAppMessage`, `type AppToFrameType`, `type FrameToAppType`, `type AppToFramePayloads`, `type FrameToAppPayloads`, `appToFrame(type, payload, { documentId, nonce })`, `frameToApp(type, payload, { documentId, nonce })`, `parseAppToFrame(data): AppToFrameMessage | null`, `parseFrameToApp(data): FrameToAppMessage | null`, `type MessageEventLike = { origin: string; source: unknown; data: unknown }`, `acceptAppMessage(event, { appOrigin, parent, nonce, documentId }): AppToFrameMessage | null`, `acceptFrameMessage(event, { editorOrigin, source, nonce, documentId }): FrameToAppMessage | null`.
  - `@clue/site-kit/editor-site`: `canonicalJson(value: unknown): string`, `getAtPath(value: unknown, path: string): unknown`, `setAtPath<T>(value: T, path: string, next: unknown): T`, `pageFor(site, route): SitePage | null`, `withPage(site, route, page): SiteDocument`, `componentProps(site, target, componentId): Record<string, unknown> | null`, `withComponentProps(site, target, componentId, props): SiteDocument`, `withAssetAt(site, target, componentId, prop, url): SiteDocument`, `internalRoute(href: string, site: SiteDocument): string | null`, `sectionDigests(site): string[]`, `type ShortcutDecision = "undo" | "redo" | "swallow" | null`, `shortcutFor(event: { key: string; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; target: unknown }): ShortcutDecision`.
  - `@clue/site-kit/editor-origin`: `EDITOR_LABEL_PATTERN = /^[0-9a-f]{32}$/`, `editorLabelFor(workspaceId: string): Promise<string>`, `editorOriginFor(label: string, suffix: string): string`, `editorLabelFromHost(host: string | undefined, suffix: string): string | null`.

- [ ] **Step 1: Write the failing tests.**

`apps/frontend/packages/site-kit/test/editor-site.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canonicalJson,
  componentProps,
  getAtPath,
  internalRoute,
  pageFor,
  sectionDigests,
  setAtPath,
  shortcutFor,
  withAssetAt,
  withComponentProps,
  withPage,
} from "../src/editor-site";
import { SiteDocumentSchema } from "../src/site-document";
import { site } from "./fixtures/garner";

const stored = site("garner-syracuse");
const document = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "Garner × Syracuse",
  theme: {},
  pages: stored.pages,
  shell: stored.shell,
  agent_sections: { AnalysisSteps: "b".repeat(64), Quote: "a".repeat(64) },
});

test("canonical JSON ignores key order and keeps array order", () => {
  assert.equal(canonicalJson({ b: 1, a: { d: [2, 1], c: null } }), canonicalJson({ a: { c: null, d: [2, 1] }, b: 1 }));
  assert.notEqual(canonicalJson({ a: [1, 2] }), canonicalJson({ a: [2, 1] }));
});

test("paths read and write nested props without mutating the original", () => {
  const props = { stats: [{ value: "7.4%", label: "x" }], slots: { headline: "Hi" } };
  assert.equal(getAtPath(props, "stats.0.value"), "7.4%");
  const next = setAtPath(props, "stats.0.value", "8%");
  assert.equal(getAtPath(next, "stats.0.value"), "8%");
  assert.equal(props.stats[0].value, "7.4%");
  assert.ok(Array.isArray(next.stats));
  assert.equal(getAtPath(setAtPath({}, "slots.headline", "New"), "slots.headline"), "New");
});

test("a page component's props are read and replaced by id, and the id is kept", () => {
  assert.equal(componentProps(document, "/", "proof")?.heading, "7.4% lower medical spend in year one. No plan changes.");
  const edited = withComponentProps(document, "/", "proof", { heading: "Edited", id: "something-else" });
  assert.equal(componentProps(edited, "/", "proof")?.heading, "Edited");
  assert.equal(componentProps(edited, "/", "proof")?.id, "proof");
  assert.equal(withComponentProps(document, "/", "missing", { heading: "x" }), document, "an unknown id changes nothing");
});

test("the header and footer are addressed through the shell target", () => {
  assert.equal(componentProps(document, "shell", "header")?.preparedFor, "Syracuse City School District");
  const edited = withComponentProps(document, "shell", "footer", { legal: "© 2027" });
  assert.equal(componentProps(edited, "shell", "footer")?.legal, "© 2027");
  assert.equal(componentProps(edited, "shell", "footer")?.id, "footer");
  assert.equal(componentProps(document, "shell", "sidebar"), null);
});

test("an asset lands at its prop path", () => {
  const url = `/asset-store/${"d".repeat(64)}`;
  const edited = withAssetAt(document, "/analysis", "what", "image", url);
  assert.equal(componentProps(edited, "/analysis", "what")?.image, url);
});

test("internal links resolve only to pages the site has", () => {
  assert.equal(internalRoute("/analysis", document), "/analysis");
  assert.equal(internalRoute("/analysis/", document), "/analysis");
  assert.equal(internalRoute("/analysis#top", document), "/analysis");
  assert.equal(internalRoute("/", document), "/");
  assert.equal(internalRoute("/pricing", document), null);
  assert.equal(internalRoute("https://garnerhealth.com/", document), null);
  assert.equal(internalRoute("//evil.example/", document), null);
});

test("withPage replaces one page; pageFor reads only the site's own routes", () => {
  const page = { root: { props: { title: "New" } }, content: [] };
  assert.equal(pageFor(withPage(document, "/analysis", page), "/analysis")?.root.props.title, "New");
  assert.equal(pageFor(document, "toString"), null);
});

test("section digests are the sorted digests of the site's agent sections", () => {
  assert.deepEqual(sectionDigests(document), ["a".repeat(64), "b".repeat(64)]);
});

test("⌘Z, ⇧⌘Z and Ctrl+Y become undo and redo, but never while typing", () => {
  const key = (value: string, extra: Partial<{ metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; target: unknown }> = {}) => ({
    ctrlKey: false,
    key: value,
    metaKey: false,
    shiftKey: false,
    target: { tagName: "DIV" },
    ...extra,
  });
  assert.equal(shortcutFor(key("z", { metaKey: true })), "undo");
  assert.equal(shortcutFor(key("Z", { metaKey: true, shiftKey: true })), "redo");
  assert.equal(shortcutFor(key("y", { ctrlKey: true })), "redo");
  assert.equal(shortcutFor(key("i", { metaKey: true })), "swallow");
  assert.equal(shortcutFor(key("z")), null);
  assert.equal(shortcutFor(key("z", { metaKey: true, target: { isContentEditable: true } })), null);
  assert.equal(shortcutFor(key("z", { ctrlKey: true, target: { tagName: "INPUT" } })), null);
});
```

`apps/frontend/packages/site-kit/test/editor-origin.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { EDITOR_LABEL_PATTERN, editorLabelFor, editorLabelFromHost, editorOriginFor } from "../src/editor-origin";

const LABEL = "aac8c47153e8e006ea26797aa03615b6"; // editorLabelFor("ws_123")

test("the label is the first 32 hex characters of sha256 over a versioned prefix", async () => {
  assert.equal(await editorLabelFor("ws_123"), LABEL);
  assert.equal(await editorLabelFor("ws_other"), "4e64151b7bc727c30d0cd033bcca9caa");
  assert.match(await editorLabelFor("ws_other"), EDITOR_LABEL_PATTERN);
});

test("a localhost suffix is http with its port; a real domain is https", () => {
  assert.equal(editorOriginFor(LABEL, "editor.localhost:3129"), `http://${LABEL}.editor.localhost:3129`);
  assert.equal(editorOriginFor(LABEL, "Edit.Example.com"), `https://${LABEL}.edit.example.com`);
  assert.throws(() => editorOriginFor("not-a-label", "edit.example.com"));
  assert.throws(() => editorOriginFor(LABEL, "https://edit.example.com"));
});

test("the label is read back from a Host header only under the configured suffix", () => {
  assert.equal(editorLabelFromHost(`${LABEL}.editor.localhost:3129`, "editor.localhost:3129"), LABEL);
  assert.equal(editorLabelFromHost(`${LABEL.toUpperCase()}.EDIT.EXAMPLE.COM`, "edit.example.com"), LABEL);
  assert.equal(editorLabelFromHost(`${LABEL}.editor.localhost:3130`, "editor.localhost:3129"), null);
  assert.equal(editorLabelFromHost(`x.${LABEL}.edit.example.com`, "edit.example.com"), null);
  assert.equal(editorLabelFromHost("edit.example.com", "edit.example.com"), null);
  assert.equal(editorLabelFromHost(undefined, "edit.example.com"), null);
});
```

`apps/frontend/packages/site-kit/test/editor-protocol.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "../src/brand";
import {
  FieldDescriptionSchema,
  acceptAppMessage,
  acceptFrameMessage,
  appToFrame,
  frameToApp,
  parseAppToFrame,
  parseFrameToApp,
} from "../src/editor-protocol";
import { SiteDocumentSchema } from "../src/site-document";

const NONCE = "nonce-0123456789abcdef";
const APP = "http://localhost:3029";
const EDITOR = "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129";
const parentWindow = { name: "app window" };
const frameWindow = { name: "editor frame" };
const ctx = { documentId: "doc_1", nonce: NONCE };
const site = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "New site",
  theme: {},
  pages: { "/": { root: { props: { title: "New site" } }, content: [] } },
  shell: null,
  agent_sections: {},
});
const brand = { slug: "x", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } as unknown as BrandData;
const GEOMETRY = {
  viewport: { x: 0, y: 10, top: 10, right: 100, bottom: 60, left: 0, width: 100, height: 50 },
  document: { x: 0, y: 410, top: 410, right: 100, bottom: 460, left: 0, width: 100, height: 50 },
};

test("every app → frame message builds and parses with its envelope", () => {
  const init = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop" }, ctx);
  assert.equal(parseAppToFrame(JSON.parse(JSON.stringify(init)))?.type, "init");
  const messages = [
    appToFrame("replace_site", { site, version: 3 }, ctx),
    appToFrame("set_mode", { mode: "preview" }, ctx),
    appToFrame("navigate", { route: "/" }, ctx),
    appToFrame("set_props", { route: "shell", componentId: "header", props: { preparedFor: "X" } }, ctx),
    appToFrame("select", { route: "/", componentId: null }, ctx),
    appToFrame("insert_asset", { route: "/", componentId: "hero", prop: "image", url: `/asset-store/${"e".repeat(64)}` }, ctx),
  ];
  for (const message of messages) assert.equal(parseAppToFrame(message)?.type, message.type);
});

test("every frame → app message parses, including the shell target and the shortcut addition", () => {
  const messages = [
    frameToApp("ready", {}, { documentId: "", nonce: NONCE }),
    frameToApp("changed", { site }, ctx),
    frameToApp("selected", { route: "shell", componentId: "header", componentType: "SiteHeader", fields: [], props: {} }, ctx),
    frameToApp("deselected", {}, ctx),
    frameToApp("navigated", { route: "/" }, ctx),
    frameToApp("request_asset", { route: "/", componentId: "hero", prop: "image" }, ctx),
    frameToApp("annotate", { route: "/", componentId: "hero", geometry: GEOMETRY }, ctx),
    frameToApp("error", { code: "section_load_failed", message: "AnalysisSteps did not load" }, ctx),
    frameToApp("shortcut", { action: "undo" }, ctx),
  ];
  for (const message of messages) assert.equal(parseFrameToApp(message)?.type, message.type);
});

test("a message off the channel, the version or the schema is dropped", () => {
  const good = frameToApp("deselected", {}, ctx);
  assert.equal(parseFrameToApp({ ...good, channel: "lumen-web-bridge" }), null);
  assert.equal(parseFrameToApp({ ...good, v: 2 }), null);
  assert.equal(parseFrameToApp({ ...good, nonce: "short" }), null);
  assert.equal(parseFrameToApp({ ...good, type: "puck:publish" }), null);
  assert.equal(parseFrameToApp({ type: "puck:publish", headline: "x" }), null);
  const insert = appToFrame("insert_asset", { route: "/", componentId: "hero", prop: "image", url: `/asset-store/${"e".repeat(64)}` }, ctx);
  assert.equal(parseAppToFrame({ ...insert, payload: { ...insert.payload, url: "https://evil.example/pixel.gif" } }), null);
  assert.equal(parseAppToFrame({ ...insert, payload: { ...insert.payload, componentId: "hero#1" } }), null);
});

test("the app accepts a frame message only from its own iframe, origin, nonce and document", () => {
  const expected = { documentId: "doc_1", editorOrigin: EDITOR, nonce: NONCE, source: frameWindow };
  const message = frameToApp("deselected", {}, ctx);
  assert.ok(acceptFrameMessage({ data: message, origin: EDITOR, source: frameWindow }, expected));
  assert.equal(acceptFrameMessage({ data: message, origin: "http://evil.editor.localhost:3129", source: frameWindow }, expected), null);
  assert.equal(acceptFrameMessage({ data: message, origin: EDITOR, source: { name: "another tab" } }, expected), null);
  assert.equal(
    acceptFrameMessage({ data: { ...message, nonce: "nonce-from-an-old-frame" }, origin: EDITOR, source: frameWindow }, expected),
    null,
  );
  assert.equal(acceptFrameMessage({ data: { ...message, documentId: "doc_old" }, origin: EDITOR, source: frameWindow }, expected), null);
  assert.equal(acceptFrameMessage({ data: message, origin: EDITOR, source: frameWindow }, { ...expected, editorOrigin: null }), null);
  // The D2 spike's ParentFrame probe: an agent section posting to its parent is not a protocol message.
  assert.equal(
    acceptFrameMessage({ data: { type: "puck:publish", headline: "x" }, origin: EDITOR, source: frameWindow }, expected),
    null,
  );
});

test("ready is accepted before any document is initialised, and only with an empty document id", () => {
  const expected = { documentId: null, editorOrigin: EDITOR, nonce: NONCE, source: frameWindow };
  const ready = frameToApp("ready", {}, { documentId: "", nonce: NONCE });
  assert.ok(acceptFrameMessage({ data: ready, origin: EDITOR, source: frameWindow }, expected));
  assert.equal(
    acceptFrameMessage({ data: frameToApp("ready", {}, ctx), origin: EDITOR, source: frameWindow }, expected),
    null,
  );
  assert.equal(
    acceptFrameMessage({ data: frameToApp("deselected", {}, ctx), origin: EDITOR, source: frameWindow }, expected),
    null,
  );
});

test("the frame accepts an app message only from its parent and the app origin; init names the document", () => {
  const expected = { appOrigin: APP, documentId: "", nonce: NONCE, parent: parentWindow };
  const init = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop" }, ctx);
  assert.ok(acceptAppMessage({ data: init, origin: APP, source: parentWindow }, expected));
  assert.equal(acceptAppMessage({ data: init, origin: "http://localhost:3030", source: parentWindow }, expected), null);
  assert.equal(acceptAppMessage({ data: init, origin: APP, source: { name: "an agent section's window" } }, expected), null);
  const mode = appToFrame("set_mode", { mode: "edit" }, ctx);
  assert.equal(acceptAppMessage({ data: mode, origin: APP, source: parentWindow }, expected), null, "no document yet");
  assert.ok(acceptAppMessage({ data: mode, origin: APP, source: parentWindow }, { ...expected, documentId: "doc_1" }));
  const unnamed = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop" }, { documentId: "", nonce: NONCE });
  assert.equal(acceptAppMessage({ data: unnamed, origin: APP, source: parentWindow }, expected), null);
});

test("field descriptions nest for lists and refuse unknown kinds", () => {
  const parsed = FieldDescriptionSchema.parse({
    kind: "list",
    label: "Stats",
    name: "stats",
    item: [{ kind: "text", label: "Value", name: "value" }],
  });
  assert.equal(parsed.item?.[0].kind, "text");
  assert.equal(FieldDescriptionSchema.safeParse({ kind: "html", label: "Stats", name: "stats" }).success, false);
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npm test -w @clue/site-kit 2>&1 | tail -6`
Expected: FAIL — `Cannot find module '../src/editor-site'` (and the two siblings).

- [ ] **Step 3: Write `editor-site.ts`.**

`apps/frontend/packages/site-kit/src/editor-site.ts`:
```ts
// The edits both sides of the editor protocol make, as pure functions over Contract 1's site
// document. The app (which saves) and the editor frame (which renders) call the SAME functions,
// so an edit can never mean two different things on the two sides of the boundary.
import { SHELL_TARGET, type SiteDocument, type SitePage, type SiteTarget } from "./site-document";

/** JSON with object keys sorted, so two equal sites compare equal whatever their key order. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, raw: unknown) => {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      return Object.fromEntries(
        Object.entries(raw as Record<string, unknown>).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
      );
    }
    return raw;
  });
}

const segmentsOf = (path: string) => path.split(".");

/** Read a dotted path ("stats.0.value", "slots.headline"). */
export function getAtPath(value: unknown, path: string): unknown {
  let cursor: unknown = value;
  for (const segment of segmentsOf(path)) {
    if (cursor === null || typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[segment];
  }
  return cursor;
}

/** Write a dotted path, copying every level along it; numeric segments index arrays. */
export function setAtPath<T>(value: T, path: string, next: unknown): T {
  const [head, ...rest] = segmentsOf(path);
  const container = value as unknown;
  const current =
    container !== null && typeof container === "object" ? (container as Record<string, unknown>)[head] : undefined;
  const child = rest.length
    ? setAtPath(current ?? (/^\d+$/.test(rest[0]) ? [] : {}), rest.join("."), next)
    : next;
  if (Array.isArray(container) && /^\d+$/.test(head)) {
    const copy = [...container];
    copy[Number(head)] = child;
    return copy as T;
  }
  const base = container !== null && typeof container === "object" ? (container as Record<string, unknown>) : {};
  return { ...base, [head]: child } as T;
}

export function pageFor(site: SiteDocument, route: string): SitePage | null {
  return Object.hasOwn(site.pages, route) ? site.pages[route] : null;
}

export function withPage(site: SiteDocument, route: string, page: SitePage): SiteDocument {
  return { ...site, pages: { ...site.pages, [route]: page } };
}

const isShellPart = (componentId: string): componentId is "header" | "footer" =>
  componentId === "header" || componentId === "footer";

/** A component's props: a page section by its `props.id`, or the shell's header/footer. */
export function componentProps(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
): Record<string, unknown> | null {
  if (target === SHELL_TARGET) {
    return site.shell && isShellPart(componentId) ? site.shell[componentId] : null;
  }
  const item = pageFor(site, target)?.content.find((entry) => entry.props.id === componentId);
  return item ? item.props : null;
}

/** Replace a component's props. The id is always kept; an unknown component changes nothing
 * (the same object comes back, so callers can tell). */
export function withComponentProps(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
  props: Record<string, unknown>,
): SiteDocument {
  if (target === SHELL_TARGET) {
    if (!site.shell || !isShellPart(componentId)) return site;
    return { ...site, shell: { ...site.shell, [componentId]: { ...props, id: componentId } } };
  }
  const page = pageFor(site, target);
  if (!page) return site;
  const index = page.content.findIndex((entry) => entry.props.id === componentId);
  if (index < 0) return site;
  const content = page.content.map((entry, position) =>
    position === index ? { ...entry, props: { ...props, id: componentId } } : entry,
  );
  return withPage(site, target, { ...page, content });
}

/** Put an `/asset-store/<sha256>` url at a component's prop path. */
export function withAssetAt(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
  prop: string,
  url: string,
): SiteDocument {
  const props = componentProps(site, target, componentId);
  if (!props) return site;
  return withComponentProps(site, target, componentId, setAtPath(props, prop, url));
}

/** The page a site-internal link points at, or null for anything else (another site, a path
 * the site has no page for, a protocol-relative url). */
export function internalRoute(href: string, site: SiteDocument): string | null {
  if (!href.startsWith("/") || href.startsWith("//")) return null;
  const path = href.split(/[?#]/, 1)[0] || "/";
  const route = path.length > 1 ? path.replace(/\/+$/, "") : path;
  return pageFor(site, route) ? route : null;
}

/** The agent-section digests a site needs, sorted (an init must re-run when this changes). */
export function sectionDigests(site: SiteDocument): string[] {
  return Object.values(site.agent_sections).sort();
}

export type ShortcutDecision = "undo" | "redo" | "swallow" | null;

/** ⌘Z / Ctrl+Z → undo, ⇧⌘Z / Ctrl+Y → redo, ⌘I → swallow (Puck's own preview toggle belongs to
 * the app's Edit button). Native text undo owns a focused input or editable text — the web
 * lane's rule (`use-inspector-writes.ts`). */
export function shortcutFor(event: {
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
  shiftKey: boolean;
  target: unknown;
}): ShortcutDecision {
  if (!event.metaKey && !event.ctrlKey) return null;
  const key = event.key.toLowerCase();
  if (key === "i") return "swallow";
  if (key !== "z" && key !== "y") return null;
  const target = event.target as { isContentEditable?: boolean; tagName?: string } | null;
  if (
    target &&
    (target.isContentEditable === true ||
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT")
  ) {
    return null;
  }
  if (key === "y") return "redo";
  return event.shiftKey ? "redo" : "undo";
}
```

- [ ] **Step 4: Write `editor-origin.ts`.**

`apps/frontend/packages/site-kit/src/editor-origin.ts`:
```ts
// Contract 9: the editor domain is one subdomain per workspace, `<label>.<suffix>`. The label is
// an opaque token derived from the workspace id (never the renameable handle): the first 32 hex
// characters of sha256 over a versioned prefix. Web Crypto, so it runs in Node and browsers.
export const EDITOR_LABEL_PATTERN = /^[0-9a-f]{32}$/;
const SUFFIX_PATTERN = /^[a-z0-9.-]+(?::\d{1,5})?$/;
const LOCAL_SUFFIX = /(^|\.)localhost(?::\d{1,5})?$/;

export async function editorLabelFor(workspaceId: string): Promise<string> {
  const bytes = new TextEncoder().encode(`clue-site-editor-label:v1:${workspaceId}`);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 32);
}

/** `https://<label>.<suffix>`; `http://` for a `*.localhost` dev suffix, which carries its port
 * (`editor.localhost:3129`). */
export function editorOriginFor(label: string, suffix: string): string {
  if (!EDITOR_LABEL_PATTERN.test(label)) throw new Error("not an editor label");
  const host = suffix.trim().toLowerCase();
  if (!SUFFIX_PATTERN.test(host)) throw new Error("not an editor domain suffix");
  return `${LOCAL_SUFFIX.test(host) ? "http" : "https"}://${label}.${host}`;
}

/** The label of a request's `Host`, or null when the host is not `<label>.<suffix>`. */
export function editorLabelFromHost(host: string | undefined, suffix: string): string | null {
  if (!host) return null;
  const value = host.trim().toLowerCase();
  const tail = `.${suffix.trim().toLowerCase()}`;
  if (!value.endsWith(tail)) return null;
  const label = value.slice(0, -tail.length);
  return EDITOR_LABEL_PATTERN.test(label) ? label : null;
}
```

- [ ] **Step 5: Write `editor-protocol.ts`.**

`apps/frontend/packages/site-kit/src/editor-protocol.ts`:
```ts
// Contract 6 (Wave 2): every message between app.cluehq.ai and the site editor frame on the
// editor domain. Both sides parse with these schemas and drop anything that does not match;
// neither side ever posts to "*". The two acceptors below are the ONLY way a side may trust a
// message: origin, source window, nonce and document id, then the schema.
//
// Refinements recorded in the master plan (Lane C plan K6): frame → app `shortcut`; the
// "shell" target in place of a route for the header/footer; `navigated` after an applied init.
import { z } from "zod";
import {
  BrandDataSchema,
  ComponentIdSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
  SiteRouteSchema,
  SiteTargetSchema,
} from "./site-document";

export const EDITOR_CHANNEL = "clue-site-editor";
export const EDITOR_PROTOCOL_VERSION = 1;

export const EditorModeSchema = z.enum(["edit", "preview"]);
export type EditorMode = z.infer<typeof EditorModeSchema>;
export const PreviewDeviceSchema = z.enum(["Desktop", "Tablet", "Mobile"]);
export type PreviewDevice = z.infer<typeof PreviewDeviceSchema>;

/** A dotted prop path: "heading", "slots.headline", "stats.0.value". */
export const PropPathSchema = z
  .string()
  .max(300)
  .regex(/^[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+))*$/);
/** Contract 1: every image in a site is a blob of this workspace's asset store. */
export const AssetStoreUrlSchema = z.string().regex(/^\/asset-store\/[0-9a-f]{64}$/);

const RectSchema = z.object({
  x: z.number(),
  y: z.number(),
  top: z.number(),
  right: z.number(),
  bottom: z.number(),
  left: z.number(),
  width: z.number(),
  height: z.number(),
});
/** The element's box in the frame's viewport and document coordinates (the web bridge's shape). */
export const GeometrySchema = z.object({ viewport: RectSchema, document: RectSchema });
export type SiteGeometry = z.infer<typeof GeometrySchema>;

export type FieldKind = "text" | "textarea" | "select" | "image" | "link" | "number" | "boolean" | "list";
export type FieldOption = { label: string; value: string | number | boolean };
export type FieldDescription = {
  name: string;
  label: string;
  kind: FieldKind;
  options?: FieldOption[];
  item?: FieldDescription[];
};
export const FieldDescriptionSchema: z.ZodType<FieldDescription> = z.lazy(() =>
  z.object({
    name: PropPathSchema,
    label: z.string().max(200),
    kind: z.enum(["text", "textarea", "select", "image", "link", "number", "boolean", "list"]),
    options: z
      .array(z.object({ label: z.string().max(200), value: z.union([z.string(), z.number(), z.boolean()]) }))
      .optional(),
    item: z.array(FieldDescriptionSchema).optional(),
  }),
);

const envelope = {
  channel: z.literal(EDITOR_CHANNEL),
  v: z.literal(EDITOR_PROTOCOL_VERSION),
  documentId: z.string().max(200),
  nonce: z.string().min(16).max(128),
};
const Props = z.record(z.string(), z.unknown());

export const AppToFrameMessageSchema = z.discriminatedUnion("type", [
  z.object({
    ...envelope,
    type: z.literal("init"),
    payload: z.object({
      site: SiteDocumentSchema,
      brand: BrandDataSchema,
      sections: z.array(SectionLinkSchema),
      mode: EditorModeSchema,
      route: SiteRouteSchema,
      device: PreviewDeviceSchema,
    }),
  }),
  z.object({
    ...envelope,
    type: z.literal("replace_site"),
    payload: z.object({ site: SiteDocumentSchema, version: z.number().int().nonnegative() }),
  }),
  z.object({ ...envelope, type: z.literal("set_mode"), payload: z.object({ mode: EditorModeSchema }) }),
  z.object({ ...envelope, type: z.literal("navigate"), payload: z.object({ route: SiteRouteSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("set_props"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, props: Props }),
  }),
  z.object({
    ...envelope,
    type: z.literal("select"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema.nullable() }),
  }),
  z.object({
    ...envelope,
    type: z.literal("insert_asset"),
    payload: z.object({
      route: SiteTargetSchema,
      componentId: ComponentIdSchema,
      prop: PropPathSchema,
      url: AssetStoreUrlSchema,
    }),
  }),
]);

export const FrameToAppMessageSchema = z.discriminatedUnion("type", [
  z.object({ ...envelope, type: z.literal("ready"), payload: z.object({}).strict() }),
  z.object({ ...envelope, type: z.literal("changed"), payload: z.object({ site: SiteDocumentSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("selected"),
    payload: z.object({
      route: SiteTargetSchema,
      componentId: ComponentIdSchema,
      componentType: z.string().min(1).max(200),
      fields: z.array(FieldDescriptionSchema),
      props: Props,
    }),
  }),
  z.object({ ...envelope, type: z.literal("deselected"), payload: z.object({}).strict() }),
  z.object({ ...envelope, type: z.literal("navigated"), payload: z.object({ route: SiteRouteSchema }) }),
  z.object({
    ...envelope,
    type: z.literal("request_asset"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, prop: PropPathSchema }),
  }),
  z.object({
    ...envelope,
    type: z.literal("annotate"),
    payload: z.object({ route: SiteTargetSchema, componentId: ComponentIdSchema, geometry: GeometrySchema }),
  }),
  z.object({
    ...envelope,
    type: z.literal("error"),
    payload: z.object({ code: z.string().min(1).max(100), message: z.string().max(2000) }),
  }),
  z.object({
    ...envelope,
    type: z.literal("shortcut"),
    payload: z.object({ action: z.enum(["undo", "redo"]) }),
  }),
]);

export type AppToFrameMessage = z.infer<typeof AppToFrameMessageSchema>;
export type FrameToAppMessage = z.infer<typeof FrameToAppMessageSchema>;
export type AppToFrameType = AppToFrameMessage["type"];
export type FrameToAppType = FrameToAppMessage["type"];
export type AppToFramePayloads = { [K in AppToFrameType]: Extract<AppToFrameMessage, { type: K }>["payload"] };
export type FrameToAppPayloads = { [K in FrameToAppType]: Extract<FrameToAppMessage, { type: K }>["payload"] };

interface EnvelopeContext {
  documentId: string;
  nonce: string;
}

export function appToFrame<T extends AppToFrameType>(
  type: T,
  payload: AppToFramePayloads[T],
  context: EnvelopeContext,
): AppToFrameMessage {
  return {
    channel: EDITOR_CHANNEL,
    v: EDITOR_PROTOCOL_VERSION,
    documentId: context.documentId,
    nonce: context.nonce,
    type,
    payload,
  } as AppToFrameMessage;
}

export function frameToApp<T extends FrameToAppType>(
  type: T,
  payload: FrameToAppPayloads[T],
  context: EnvelopeContext,
): FrameToAppMessage {
  return {
    channel: EDITOR_CHANNEL,
    v: EDITOR_PROTOCOL_VERSION,
    documentId: context.documentId,
    nonce: context.nonce,
    type,
    payload,
  } as FrameToAppMessage;
}

export function parseAppToFrame(data: unknown): AppToFrameMessage | null {
  const parsed = AppToFrameMessageSchema.safeParse(data);
  return parsed.success ? parsed.data : null;
}

export function parseFrameToApp(data: unknown): FrameToAppMessage | null {
  const parsed = FrameToAppMessageSchema.safeParse(data);
  return parsed.success ? parsed.data : null;
}

export interface MessageEventLike {
  origin: string;
  source: unknown;
  data: unknown;
}

/** The frame's rule: from its own parent, from the app origin, with its nonce. `init` names the
 * document the frame then belongs to; every other message must name that document. */
export function acceptAppMessage(
  event: MessageEventLike,
  expected: { appOrigin: string; documentId: string; nonce: string; parent: unknown },
): AppToFrameMessage | null {
  if (expected.parent == null || event.source !== expected.parent) return null;
  if (event.origin !== expected.appOrigin) return null;
  const message = parseAppToFrame(event.data);
  if (!message || message.nonce !== expected.nonce) return null;
  if (message.type === "init") return message.documentId === "" ? null : message;
  if (expected.documentId === "" || message.documentId !== expected.documentId) return null;
  return message;
}

/** The app's rule: from the iframe it mounted, from the workspace's exact editor origin, with
 * that frame's nonce. `ready` (the frame's boot) carries no document; everything else must
 * name the document the app last initialised the frame with. */
export function acceptFrameMessage(
  event: MessageEventLike,
  expected: { documentId: string | null; editorOrigin: string | null; nonce: string | null; source: unknown },
): FrameToAppMessage | null {
  if (!expected.editorOrigin || event.origin !== expected.editorOrigin) return null;
  if (expected.source == null || event.source !== expected.source) return null;
  const message = parseFrameToApp(event.data);
  if (!message || !expected.nonce || message.nonce !== expected.nonce) return null;
  if (message.type === "ready") return message.documentId === "" ? message : null;
  if (expected.documentId === null || message.documentId !== expected.documentId) return null;
  return message;
}
```

In `apps/frontend/packages/site-kit/package.json`, extend `"exports"` (after `"./site-document"`):
```json
    "./editor-protocol": "./src/editor-protocol.ts",
    "./editor-site": "./src/editor-site.ts",
    "./editor-origin": "./src/editor-origin.ts"
```

- [ ] **Step 6: Run the site-kit suite and its type-check.**

Run: `cd apps/frontend && npm test -w @clue/site-kit 2>&1 | tail -6 && npm run typecheck -w @clue/site-kit`
Expected: `# fail 0` (the new files add 9 + 3 + 7 = 19 tests) and no type errors.

- [ ] **Step 7: Check the protocol refinements are in the master plan.** The controller recorded
K6 in Contract 6 at the 2026-10-11 review. Confirm, and correct the bullets if this task's schemas
came out differently:

```bash
grep -n 'Refinements (Lane C plan, 2026-10-11, K6' -A6 docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md
```

Expected: the four bullets (`shortcut`, the `"shell"` route, `navigated`, the component-id pattern)
and the `editor-protocol.ts` line are printed.

- [ ] **Step 8: Write the canonical architecture document and index it.**

`apps/frontend/docs/architecture/site-editor.md`:
```markdown
# Site editor (Puck sites, Wave 2 Lane C)

Status: implementation in progress (plan `docs/superpowers/plans/2026-10-11-lane-c-site-editor.md`).

## Two origins
- **The app** (`app.cluehq.ai`, `apps/frontend`) holds the session, the chat, the stage chrome,
  the dock (fields + Layers), the asset library, versions and publish. It holds the site JSON
  and is the only side that saves (design API site routes through `/api/clue/design/*`).
- **The editor domain** (`https://<label>.<CLUE_SITE_EDITOR_SUFFIX>`, `apps/frontend/packages/site-editor`)
  renders the Puck canvas (`Puck.Preview` only) and runs agent-written sections. It has no
  login, a strict CSP (no unsafe-eval, nonced import map only, frame-ancestors = the app), and
  serves `/sections/<digest>.mjs?t=` (token verified with the design API) and `/asset-store/<sha>`
  (proxied) from its own origin. `<label>` = first 32 hex of sha256("clue-site-editor-label:v1:" + workspace id).

## The protocol
`@clue/site-kit/editor-protocol` (Contract 6). Envelope `{channel: "clue-site-editor", v: 1,
documentId, nonce, type, payload}`. The app accepts only from its iframe's window, the exact
editor origin, the frame's nonce and the initialised document; the frame only from its parent
and the app origin. No `"*"` target origins.

## Where the code is
- Kind switch: `src/features/chat-shell/model/artifact-kind.ts` (`isWebsiteKind`, `chatShellKindForCard`).
- Data + save policy: `src/features/site-editor/{model,data,hooks}`.
- Frame host: `src/features/design-editor/components/site-artifact-canvas.tsx`, persistent in `artifact-stage.tsx`.
- Dock: `src/features/chat-shell/components/site-inspector.tsx`; pages: `site-pages-panel.tsx`, `site-url-bar.tsx`.
- Shared edits: `@clue/site-kit/editor-site`; origin helpers: `@clue/site-kit/editor-origin`.
```

In `apps/frontend/docs/README.md`, add under `## Canonical documents`, directly after the `architecture/frontend.md` bullet:
```markdown
- [`architecture/site-editor.md`](architecture/site-editor.md) — the Puck site
  editor: the app/editor-domain split, the frame protocol and where the code lives.
```

- [ ] **Step 9: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 10: Commit.**
```bash
git add apps/frontend/packages/site-kit docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md apps/frontend/docs/architecture/site-editor.md apps/frontend/docs/README.md
git commit -m "site-kit: the editor protocol (Contract 6) with both acceptors, shared site edits and the per-workspace editor origin"
```

---

### Task 5: C3b — the editor app's server (static SPA + a tiny `node:http` server)

**Why a static single-page app plus a small server, not a second Next app.** The editor domain must send a strict CSP with no `'unsafe-eval'`, no `'strict-dynamic'` and no un-nonced inline script, must carry no Clerk, must serve `/sections/<digest>.mjs` and `/asset-store/<sha>` from its own origin, and must behave the same in dev as in production (Review focus 6 is a browser test). Next App Router needs a nonce CSP from `proxy.ts` with dynamic rendering, injects its own inline scripts, and in development needs `'unsafe-eval'` (`node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md:42`) — so a dev editor would be *weaker* than production, exactly where the containment test runs. A static page (one HTML file, one esbuild bundle, one stylesheet, three shim files) with a ~200-line server gives full control of every header, no inline script but the nonced import map, the same CSP in dev and production, and a 30 MB runtime image. The server's only dynamic routes are the token-verified section route and the asset-store proxy.

This task builds the server and its tests; Task 6 builds the client and the build script.

**Files:**
- Create: `apps/frontend/packages/site-editor/package.json`
- Create: `apps/frontend/packages/site-editor/tsconfig.json`
- Create: `apps/frontend/packages/site-editor/.env.example`
- Create: `apps/frontend/packages/site-editor/src/server/config.ts`
- Create: `apps/frontend/packages/site-editor/src/server/csp.ts`
- Create: `apps/frontend/packages/site-editor/src/server/app.ts`
- Create: `apps/frontend/packages/site-editor/src/server/main.ts`
- Create: `apps/frontend/packages/site-editor/test/server.test.ts`
- Modify: `apps/frontend/package-lock.json` (via `npm install`)
- Modify: `apps/frontend/Dockerfile.railway` (copy the new manifest before `npm ci`)
- Modify: `apps/frontend/eslint.config.mjs` (ignore `packages/*/dist/**`)
- Modify: `.env.example`, `.env` (untracked), `apps/frontend/.env.example` (`CLUE_SITE_EDITOR_SUFFIX`, default `edit.deeppresence.ai`)

**Interfaces:**
- Consumes: `@clue/site-kit/editor-origin` (`editorLabelFor`, `editorLabelFromHost`) from Task 4; plan assumption K1 (design-API routes `GET /site-sections/{digest}.mjs|css?t=` answering `X-Clue-Workspace-Id`).
- Produces:
  - `src/server/config.ts`: `interface EditorServerConfig { port: number; host: string; appOrigin: string; designApiBaseUrl: string; editorSuffix: string; distDir: string }`, `readConfig(env: Record<string, string | undefined>, distDir: string): EditorServerConfig` (env keys `PORT`, `HOST`, `CLUE_APP_ORIGIN`, `LUMEN_API_BASE_URL`, `CLUE_SITE_EDITOR_SUFFIX`).
  - `src/server/csp.ts`: `contentSecurityPolicy(options: { appOrigin: string; nonce: string | null }): string`, `SECURITY_HEADERS: Readonly<Record<string, string>>`.
  - `src/server/app.ts`: `interface EditorRequest { method: string; url: string; host: string | undefined }`, `interface EditorResponse { status: number; headers: Record<string, string>; body: string | Uint8Array | ReadableStream<Uint8Array> | null }`, `handleEditorRequest(request: EditorRequest, deps: { config: EditorServerConfig; fetchImpl?: typeof fetch; readFile?: (file: string) => Promise<Uint8Array>; nonce?: () => string }): Promise<EditorResponse>`.
  - Routes: `GET /healthz` (any host); on `<label>.<suffix>` only: `GET /` and `/index.html` (the page, `%NONCE%` and `%APP_ORIGIN%` filled), `/assets/<name>.js|.css` (immutable), `/shims/{react,react-jsx-runtime,zod}.mjs`, `/sections/<64 hex>.mjs|.css?t=<token>`, `/asset-store/<64 hex>`.

- [ ] **Step 1: Create the package skeleton and install it into the workspace.**

`apps/frontend/packages/site-editor/package.json`:
```json
{
  "name": "@clue/site-editor",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "tsx --test test/*.test.ts",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@clue/site-kit": "*",
    "@puckeditor/core": "0.23.0",
    "react": "19.2.4",
    "react-dom": "19.2.4",
    "zod": "^4.4.3"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4",
    "@types/jsdom": "^30.0.0",
    "@types/node": "^20",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "esbuild": "^0.28.2",
    "jsdom": "^29.1.1",
    "postcss": "8.5.23",
    "tailwindcss": "^4",
    "tsx": "^4.23.1",
    "typescript": "^5"
  }
}
```

`apps/frontend/packages/site-editor/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "lib": ["dom", "dom.iterable", "esnext"],
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "types": ["node"]
  },
  "include": ["src", "test"]
}
```

`apps/frontend/packages/site-editor/.env.example`:
```bash
# The site editor app (apps/frontend/packages/site-editor), served on the editor domain
# https://<label>.<CLUE_SITE_EDITOR_SUFFIX>. Every key is read by src/server/config.ts.
# In dev, scripts/dev_stack.sh passes these per process; on Railway they are service variables.
PORT=3120
# 127.0.0.1 in dev; 0.0.0.0 on Railway.
HOST=127.0.0.1
# The app origin allowed to frame the editor (CSP frame-ancestors) and to message it.
CLUE_APP_ORIGIN=http://localhost:3020
# The design API (server-side only): token-verified agent sections and the public asset store.
LUMEN_API_BASE_URL=http://127.0.0.1:8010
# The editor domain suffix; dev is editor.localhost:<PORT> (browsers resolve *.localhost to loopback).
CLUE_SITE_EDITOR_SUFFIX=editor.localhost:3120
```

The editor server introduces `CLUE_SITE_EDITOR_SUFFIX`, so the parity rule puts it in the repo's env files now (Contract 9 names both `.env` and `.env.example`). In `.env.example`, add this block directly after the `# --- Public pages: hostnames and delivery …` block (after `CLUE_PAGES_ORIGIN_PORT=8040`), and add the same block to the local `.env` (untracked; edit, never commit):
```bash
# --- Site editor domain (Wave 2 Contract 9; Lane C) ---------------------------------------------
# The Puck site editor is served at https://<label>.<CLUE_SITE_EDITOR_SUFFIX>, one subdomain per
# workspace (<label> = an opaque token derived from the workspace id). Empty = no editor domain is
# configured, and a site shows the canvas's error state. Founder's choice (Lane C plan Q1,
# 2026-10-12): edit.deeppresence.ai, a registrable domain nothing else with a login uses.
# scripts/dev_stack.sh overrides it per process with editor.localhost:<port>.
CLUE_SITE_EDITOR_SUFFIX=edit.deeppresence.ai
```
In `apps/frontend/.env.example`, append:
```bash

# Wave 2 Contract 9: the site editor's domain suffix; the app frames https://<label>.<suffix>.
# Empty = no editor domain (a site shows the canvas error state). scripts/dev_stack.sh passes
# editor.localhost:<DEV_STACK_EDITOR_PORT> to the dev frontend process.
CLUE_SITE_EDITOR_SUFFIX=edit.deeppresence.ai
```

Run: `cd apps/frontend && npm install`
Expected: exits 0; `git status --short package-lock.json` shows ` M package-lock.json`; `ls node_modules/@clue/` lists `design-system  site-editor  site-kit`.

- [ ] **Step 2: Watch the Task 1 guard fail on the new package, then fix the Dockerfile.**

Run: `.venv/bin/python -m pytest tests/deploy/test_frontend_image.py -q`
Expected: FAIL — `does not copy apps/frontend/packages/site-editor/package.json before npm ci`.

In `apps/frontend/Dockerfile.railway`, add directly after the site-kit `COPY` line:
```dockerfile
COPY apps/frontend/packages/site-editor/package.json ./packages/site-editor/package.json
```
Run the guard again. Expected: `1 passed`.

In `apps/frontend/eslint.config.mjs`, add inside `globalIgnores([ … ])` after `"public/vendor/**",`:
```js
    // Built workspace-package output (the site editor's dist/), not lintable source.
    "packages/*/dist/**",
```

- [ ] **Step 3: Write the failing server tests.**

`apps/frontend/packages/site-editor/test/server.test.ts`:
```ts
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { before, test } from "node:test";
import { editorLabelFor } from "@clue/site-kit/editor-origin";
import { handleEditorRequest, type EditorResponse } from "../src/server/app";
import { readConfig, type EditorServerConfig } from "../src/server/config";
import { contentSecurityPolicy } from "../src/server/csp";

const APP = "http://localhost:3029";
const SUFFIX = "editor.localhost:3129";
const DIGEST = "a".repeat(64);
const TOKEN = "tok_0123456789abcdef";
let LABEL = "";
let HOST = "";
let config: EditorServerConfig;

before(async () => {
  LABEL = await editorLabelFor("ws_123");
  HOST = `${LABEL}.${SUFFIX}`;
  const dist = await fs.mkdtemp(path.join(os.tmpdir(), "site-editor-dist-"));
  await fs.mkdir(path.join(dist, "assets"));
  await fs.mkdir(path.join(dist, "shims"));
  await fs.writeFile(
    path.join(dist, "index.html"),
    '<meta name="clue-app-origin" content="%APP_ORIGIN%"><script type="importmap" nonce="%NONCE%">{}</script>',
  );
  await fs.writeFile(path.join(dist, "assets", "editor-abc123.js"), "console.log(1)");
  await fs.writeFile(path.join(dist, "shims", "react.mjs"), "export default 1");
  config = readConfig(
    { CLUE_APP_ORIGIN: APP, CLUE_SITE_EDITOR_SUFFIX: SUFFIX, LUMEN_API_BASE_URL: "http://127.0.0.1:8019/", PORT: "3129" },
    dist,
  );
});

function get(url: string, extra: Partial<Parameters<typeof handleEditorRequest>[1]> = {}, host: string | undefined = HOST) {
  return handleEditorRequest({ host, method: "GET", url }, { config, nonce: () => "fixed-nonce-0123456789", ...extra });
}

async function text(response: EditorResponse): Promise<string> {
  if (response.body === null) return "";
  if (typeof response.body === "string") return response.body;
  if (response.body instanceof Uint8Array) return new TextDecoder().decode(response.body);
  return new Response(response.body).text();
}

test("configuration refuses a missing or malformed setting", () => {
  const good = { CLUE_APP_ORIGIN: APP, CLUE_SITE_EDITOR_SUFFIX: SUFFIX, LUMEN_API_BASE_URL: "http://127.0.0.1:8019" };
  assert.equal(readConfig(good, "/dist").port, 3120);
  assert.equal(readConfig(good, "/dist").host, "127.0.0.1");
  assert.throws(() => readConfig({ ...good, CLUE_APP_ORIGIN: "" }, "/dist"));
  assert.throws(() => readConfig({ ...good, CLUE_APP_ORIGIN: "http://localhost:3029/path" }, "/dist"));
  assert.throws(() => readConfig({ ...good, LUMEN_API_BASE_URL: "" }, "/dist"));
  assert.throws(() => readConfig({ ...good, CLUE_SITE_EDITOR_SUFFIX: "" }, "/dist"));
});

test("the content security policy is the one D2 and the plan's Global Constraints name", () => {
  const policy = contentSecurityPolicy({ appOrigin: APP, nonce: "abc123def456ghi789" });
  for (const directive of [
    "default-src 'none'",
    "script-src 'self' 'nonce-abc123def456ghi789'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "media-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    `frame-ancestors ${APP}`,
  ]) {
    assert.ok(policy.includes(directive), directive);
  }
  for (const forbidden of ["unsafe-eval", "strict-dynamic", "blob:", "*"]) {
    assert.equal(policy.includes(forbidden), false, forbidden);
  }
  assert.equal(contentSecurityPolicy({ appOrigin: APP, nonce: null }).includes("script-src 'self';"), true);
});

test("the page carries a fresh nonce in both its import map and its policy, and the app origin", async () => {
  const response = await get("/");
  assert.equal(response.status, 200);
  assert.equal(response.headers["content-type"], "text/html; charset=utf-8");
  assert.equal(response.headers["cache-control"], "no-store");
  assert.ok(response.headers["content-security-policy"].includes("'nonce-fixed-nonce-0123456789'"));
  assert.equal(response.headers["x-content-type-options"], "nosniff");
  assert.equal(response.headers["referrer-policy"], "no-referrer");
  const html = await text(response);
  assert.ok(html.includes('nonce="fixed-nonce-0123456789"'));
  assert.ok(html.includes(`content="${APP}"`));
});

test("only <label>.<suffix> hosts are served; the health check answers any host", async () => {
  assert.equal((await get("/", {}, `${SUFFIX}`)).status, 404);
  assert.equal((await get("/", {}, `not-a-label.${SUFFIX}`)).status, 404);
  assert.equal((await get("/", {}, undefined)).status, 404);
  assert.equal((await get("/healthz", {}, "railway.internal:3120")).status, 200);
});

test("only GET and HEAD are allowed", async () => {
  const response = await handleEditorRequest({ host: HOST, method: "POST", url: "/" }, { config });
  assert.equal(response.status, 405);
});

test("built assets are immutable; anything outside the asset list is 404", async () => {
  const asset = await get("/assets/editor-abc123.js");
  assert.equal(asset.status, 200);
  assert.equal(asset.headers["content-type"], "text/javascript; charset=utf-8");
  assert.equal(asset.headers["cache-control"], "public, max-age=31536000, immutable");
  assert.equal((await get("/assets/..%2Findex.html")).status, 404);
  assert.equal((await get("/assets/editor-abc123.exe")).status, 404);
  assert.equal((await get("/assets/missing.js")).status, 404);
  assert.equal((await get("/shims/react.mjs")).status, 200);
  assert.equal((await get("/shims/lodash.mjs")).status, 404);
});

test("a section loads only with a token the design API verifies for THIS workspace", async () => {
  const calls: string[] = [];
  const upstream = (workspaceId: string, status = 200) =>
    (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response("export const schema = {}; export function render() { return null; }", {
        headers: { "content-type": "text/javascript", "x-clue-workspace-id": workspaceId },
        status,
      });
    }) as typeof fetch;

  assert.equal((await get(`/sections/${DIGEST}.mjs`, { fetchImpl: upstream("ws_123") })).status, 404, "no token");
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=short`, { fetchImpl: upstream("ws_123") })).status, 404, "bad token");
  assert.equal(calls.length, 0, "a malformed request never reaches the design API");

  const ok = await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_123") });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers["content-type"], "text/javascript; charset=utf-8");
  assert.equal(ok.headers["cache-control"], "private, no-store");
  assert.equal(calls.at(-1), `http://127.0.0.1:8019/site-sections/${DIGEST}.mjs?t=${TOKEN}`);

  // Review focus 4 (master plan): workspace B's module never loads on workspace A's origin.
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_other") })).status, 404);
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_123", 403) })).status, 404);

  const css = await get(`/sections/${DIGEST}.css?t=${TOKEN}`, { fetchImpl: upstream("ws_123") });
  assert.equal(css.headers["content-type"], "text/css; charset=utf-8");
});

test("the asset store is proxied headerlessly with only content-type and cache-control kept", async () => {
  const seen: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ init, url: String(input) });
    return new Response("png-bytes", {
      headers: {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": "image/png",
        "set-cookie": "upstream=must-not-leak",
      },
    });
  }) as typeof fetch;
  const response = await get(`/asset-store/${DIGEST}`, { fetchImpl });
  assert.equal(response.status, 200);
  assert.equal(response.headers["content-type"], "image/png");
  assert.equal(response.headers["set-cookie"], undefined);
  assert.equal(seen[0].url, `http://127.0.0.1:8019/asset-store/${DIGEST}`);
  assert.deepEqual([...new Headers(seen[0].init?.headers ?? {}).keys()], []);
  assert.equal(seen[0].init?.redirect, "manual");
  assert.equal(await text(response), "png-bytes");
  assert.equal((await get("/asset-store/not-a-digest", { fetchImpl })).status, 404);
});
```

- [ ] **Step 4: Run them to verify they fail.**

Run: `cd apps/frontend && npm test -w @clue/site-editor 2>&1 | tail -5`
Expected: FAIL — `Cannot find module '../src/server/app'`.

- [ ] **Step 5: Write the configuration and the policy.**

`apps/frontend/packages/site-editor/src/server/config.ts`:
```ts
export interface EditorServerConfig {
  port: number;
  host: string;
  appOrigin: string;
  designApiBaseUrl: string;
  editorSuffix: string;
  distDir: string;
}

function requireOrigin(raw: string | undefined, name: string): string {
  const value = (raw ?? "").trim().replace(/\/$/, "");
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute http(s) origin`);
  }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.origin !== value) {
    throw new Error(`${name} must be an absolute http(s) origin without a path`);
  }
  return parsed.origin;
}

/** Every setting the editor server reads, refused loudly when missing (apps/frontend/packages/site-editor/.env.example). */
export function readConfig(env: Record<string, string | undefined>, distDir: string): EditorServerConfig {
  const designApiBaseUrl = (env.LUMEN_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  if (!/^https?:\/\/[^/]+/.test(designApiBaseUrl)) throw new Error("LUMEN_API_BASE_URL is required");
  const editorSuffix = (env.CLUE_SITE_EDITOR_SUFFIX ?? "").trim().toLowerCase();
  if (!editorSuffix) throw new Error("CLUE_SITE_EDITOR_SUFFIX is required");
  const port = Number.parseInt(env.PORT ?? "3120", 10);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) throw new Error("PORT must be a TCP port");
  return {
    appOrigin: requireOrigin(env.CLUE_APP_ORIGIN, "CLUE_APP_ORIGIN"),
    designApiBaseUrl,
    distDir,
    editorSuffix,
    host: (env.HOST ?? "").trim() || "127.0.0.1",
    port,
  };
}
```

`apps/frontend/packages/site-editor/src/server/csp.ts`:
```ts
/**
 * The editor domain's content security policy (D2 + plan Global Constraints). The only inline
 * script is the import map, allowed by a per-response nonce; there is no 'unsafe-eval' (zod
 * runs jitless), no 'strict-dynamic' (an agent module may not import anything the policy does
 * not name) and no blob:. Images, fonts and media come only from this origin's /asset-store
 * proxy (or data:). Puck's in-frame canvas iframe is disabled, so no frames at all.
 */
export function contentSecurityPolicy({ appOrigin, nonce }: { appOrigin: string; nonce: string | null }): string {
  return [
    "default-src 'none'",
    nonce ? `script-src 'self' 'nonce-${nonce}'` : "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "media-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
    "worker-src 'none'",
    "object-src 'none'",
    "manifest-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    `frame-ancestors ${appOrigin}`,
  ].join("; ");
}

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};
```

- [ ] **Step 6: Write the request handler and the process entry.**

`apps/frontend/packages/site-editor/src/server/app.ts`:
```ts
import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { editorLabelFor, editorLabelFromHost } from "@clue/site-kit/editor-origin";
import type { EditorServerConfig } from "./config";
import { contentSecurityPolicy, SECURITY_HEADERS } from "./csp";

export interface EditorRequest {
  method: string;
  url: string;
  host: string | undefined;
}

export interface EditorResponse {
  status: number;
  headers: Record<string, string>;
  body: string | Uint8Array | ReadableStream<Uint8Array> | null;
}

export interface EditorServerDeps {
  config: EditorServerConfig;
  fetchImpl?: typeof fetch;
  readFile?: (file: string) => Promise<Uint8Array>;
  nonce?: () => string;
}

const ASSET_NAME = /^[A-Za-z0-9._-]+$/;
const SHIM_NAMES = new Set(["react.mjs", "react-jsx-runtime.mjs", "zod.mjs"]);
const SECTION_PATH = /^\/sections\/([0-9a-f]{64})\.(mjs|css)$/;
const ASSET_STORE_PATH = /^\/asset-store\/([0-9a-f]{64})$/;
const TOKEN = /^[A-Za-z0-9._~-]{16,2048}$/;
const SCRIPT = "text/javascript; charset=utf-8";
const STYLE = "text/css; charset=utf-8";
const PLAIN = "text/plain; charset=utf-8";
const ASSET_TYPES: Record<string, string> = { ".css": STYLE, ".js": SCRIPT };
const ASSET_STORE_HEADERS = ["content-type", "cache-control"] as const;

function respond(
  config: EditorServerConfig,
  status: number,
  body: EditorResponse["body"],
  headers: Record<string, string>,
  nonce: string | null = null,
): EditorResponse {
  return {
    body,
    headers: {
      ...SECURITY_HEADERS,
      "content-security-policy": contentSecurityPolicy({ appOrigin: config.appOrigin, nonce }),
      ...headers,
    },
    status,
  };
}

const notFound = (config: EditorServerConfig) =>
  respond(config, 404, "Not found", { "cache-control": "no-store", "content-type": PLAIN });

async function readOrNull(readFile: (file: string) => Promise<Uint8Array>, file: string): Promise<Uint8Array | null> {
  try {
    return await readFile(file);
  } catch {
    return null;
  }
}

export async function handleEditorRequest(request: EditorRequest, deps: EditorServerDeps): Promise<EditorResponse> {
  const { config } = deps;
  const fetchImpl = deps.fetchImpl ?? fetch;
  const readFile = deps.readFile ?? ((file: string) => fs.readFile(file));
  const url = new URL(request.url, "http://editor.invalid");

  if (url.pathname === "/healthz") {
    return respond(config, 200, "ok", { "cache-control": "no-store", "content-type": PLAIN });
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return respond(config, 405, "Method not allowed", { allow: "GET, HEAD", "content-type": PLAIN });
  }
  const label = editorLabelFromHost(request.host, config.editorSuffix);
  if (!label) return notFound(config);

  if (url.pathname === "/" || url.pathname === "/index.html") {
    const nonce = (deps.nonce ?? (() => randomBytes(18).toString("base64url")))();
    const template = await readOrNull(readFile, path.join(config.distDir, "index.html"));
    if (!template) return respond(config, 503, "The editor is not built", { "content-type": PLAIN });
    const html = new TextDecoder()
      .decode(template)
      .replaceAll("%NONCE%", nonce)
      .replaceAll("%APP_ORIGIN%", config.appOrigin);
    return respond(config, 200, html, { "cache-control": "no-store", "content-type": "text/html; charset=utf-8" }, nonce);
  }

  if (url.pathname.startsWith("/assets/")) {
    const name = url.pathname.slice("/assets/".length);
    const type = ASSET_TYPES[path.extname(name)];
    if (!ASSET_NAME.test(name) || !type) return notFound(config);
    const body = await readOrNull(readFile, path.join(config.distDir, "assets", name));
    if (!body) return notFound(config);
    return respond(config, 200, body, {
      "cache-control": "public, max-age=31536000, immutable",
      "content-type": type,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  if (url.pathname.startsWith("/shims/")) {
    const name = url.pathname.slice("/shims/".length);
    if (!SHIM_NAMES.has(name)) return notFound(config);
    const body = await readOrNull(readFile, path.join(config.distDir, "shims", name));
    if (!body) return notFound(config);
    return respond(config, 200, body, {
      "cache-control": "public, max-age=300",
      "content-type": SCRIPT,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  const section = SECTION_PATH.exec(url.pathname);
  if (section) {
    const [, digest, extension] = section;
    const token = url.searchParams.get("t") ?? "";
    if (!TOKEN.test(token)) return notFound(config);
    let upstream: Response;
    try {
      upstream = await fetchImpl(
        `${config.designApiBaseUrl}/site-sections/${digest}.${extension}?t=${encodeURIComponent(token)}`,
        { redirect: "manual" },
      );
    } catch {
      return respond(config, 502, "Section unavailable", { "cache-control": "no-store", "content-type": PLAIN });
    }
    if (upstream.status !== 200) return notFound(config);
    const workspaceId = upstream.headers.get("x-clue-workspace-id");
    // Tenant isolation: the module must belong to the workspace whose label is this origin.
    if (!workspaceId || (await editorLabelFor(workspaceId)) !== label) return notFound(config);
    return respond(config, 200, new Uint8Array(await upstream.arrayBuffer()), {
      "cache-control": "private, no-store",
      "content-type": extension === "mjs" ? SCRIPT : STYLE,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  const asset = ASSET_STORE_PATH.exec(url.pathname);
  if (asset) {
    // The same narrow passthrough as the app's /api/clue/design-public route: GET only, a content
    // address, zero request headers forwarded, two response headers kept.
    const upstream = await fetchImpl(`${config.designApiBaseUrl}/asset-store/${asset[1]}`, { redirect: "manual" });
    const headers: Record<string, string> = { "cross-origin-resource-policy": "same-origin" };
    for (const name of ASSET_STORE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) headers[name] = value;
    }
    return respond(config, upstream.status, upstream.body, headers);
  }

  return notFound(config);
}
```

`apps/frontend/packages/site-editor/src/server/main.ts`:
```ts
// The site editor's process entry. Built by scripts/build.mjs into dist/server.mjs, which lives
// next to the built page (dist/index.html), the bundle (dist/assets/) and the shims (dist/shims/).
import http from "node:http";
import path from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import { handleEditorRequest } from "./app";
import { readConfig } from "./config";

const config = readConfig(process.env, path.dirname(fileURLToPath(import.meta.url)));

const server = http.createServer((request, response) => {
  handleEditorRequest({ host: request.headers.host, method: request.method ?? "GET", url: request.url ?? "/" }, { config })
    .then((result) => {
      response.writeHead(result.status, result.headers);
      if (request.method === "HEAD" || result.body === null) {
        response.end();
        return;
      }
      if (result.body instanceof ReadableStream) {
        Readable.fromWeb(result.body as Parameters<typeof Readable.fromWeb>[0]).pipe(response);
        return;
      }
      response.end(result.body);
    })
    .catch((error: unknown) => {
      console.error("site editor: request failed", error);
      if (!response.headersSent) response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end("Internal error");
    });
});

server.listen(config.port, config.host, () => {
  console.log(`site editor listening on http://${config.host}:${config.port} for *.${config.editorSuffix}`);
});
```

- [ ] **Step 7: Run the tests and the package type-check.**

Run: `cd apps/frontend && npm test -w @clue/site-editor 2>&1 | tail -5 && npm run typecheck -w @clue/site-editor`
Expected: 8 passing, 0 failing; no type errors.

- [ ] **Step 8: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0 (the frontend's `tsconfig.json` includes `packages/**`, so `next build` type-checks the new package too).

- [ ] **Step 9: Commit.**
```bash
git add apps/frontend/packages/site-editor apps/frontend/package-lock.json apps/frontend/Dockerfile.railway apps/frontend/eslint.config.mjs .env.example apps/frontend/.env.example
git commit -m "site editor: the editor domain's server — strict nonce CSP, label-checked hosts, token-verified section route, asset-store proxy"
```

---

### Task 6: C3c — the editor app's client (Puck canvas only, runtime sections, Contract 6) and its build

The page the editor domain serves renders exactly one thing: `<Puck>` composed with `<Puck.Preview />` alone (no fields, no outline, no header — those live in the app's dock, founder ruling). Puck's own nested canvas iframe is turned off (`iframe={{ enabled: false }}`): the editor document *is* the device-width canvas (the stage pins the iframe's width), so media queries still resolve against the device, element geometry is already in this frame's viewport, and there is no nested frame for keyboard handling or style syncing.

Agent sections load at runtime with the spike's mechanism adapted to the CSP (`trials/puck-spike/app/edit-runtime/[site]/page.tsx:18-63`): the editor puts its own `react`, `react/jsx-runtime` and `zod` on `globalThis.__clueSectionHost`, a nonced import map points those three specifiers at static shim files on this origin (`/shims/*.mjs`, not `data:` URLs), and each section is `import()`ed from `/sections/<digest>.mjs?t=<token>` (Task 5's route) with its per-module CSS from `/sections/<digest>.css?t=<token>`. zod is set jitless before any schema is parsed.

All frame-side decisions live in a plain `FrameController` (testable without a DOM); `editor-app.tsx` only wires Puck, the window listeners and the controller.

**Files:**
- Create: `apps/frontend/packages/site-editor/scripts/build.ts`
- Create: `apps/frontend/packages/site-editor/scripts/dev.ts`
- Create: `apps/frontend/packages/site-editor/src/client/{jitless.ts,host-globals.ts,boot.ts,sections.ts,fields.ts,config.tsx,dom.ts,frame-controller.ts,editor-app.tsx,main.tsx,styles.css}`
- Create: `apps/frontend/packages/site-editor/test/{boot,sections,fields,dom,frame-controller,build}.test.ts`
- Create: `apps/frontend/packages/site-editor/test/browser/fixture-init.ts`
- Create: `tests/site_editor/__init__.py`, `tests/site_editor/conftest.py`, `tests/site_editor/test_editor_renders.py`
- Modify: `apps/frontend/packages/site-editor/package.json` (`scripts`), `apps/frontend/packages/site-editor/tsconfig.json` (`include`)

**Interfaces:**
- Consumes: Task 3 (`@clue/site-kit/site-document`), Task 4 (`@clue/site-kit/editor-protocol`, `@clue/site-kit/editor-site`), Task 5 (the server and its routes), site-kit's `makeConfig`, `AgentSectionModule`, `BrandData`, `ShellData` (`@clue/site-kit`) and `AssetPicker`, `CloneEditor` (`@clue/site-kit/editor`).
- Produces:
  - `scripts/build.ts`: `ROOT`, `DIST`, `SHIMS`, `IMPORT_MAP: string`, `shimSource(specifier: string, names: readonly string[]): string`, `pageHtml(scriptName: string, styleName: string): string`, `compileStyles(): Promise<string>`, `buildClient(): Promise<void>`, `buildServer(): Promise<void>`, `buildAll(): Promise<void>`; `dist/` = `index.html`, `assets/editor-<hash>.js|.css`, `shims/{react,react-jsx-runtime,zod}.mjs`, `server.mjs`.
  - `src/client/fields.ts`: `humanize(name: string): string`, `describeFields(fields: Fields, hidden?: readonly string[]): FieldDescription[]`, `clonedSectionFields(brand: BrandData, props: Record<string, unknown>): FieldDescription[]`, `fieldsForComponent(config: Config, brand: BrandData, type: string, props: Record<string, unknown>): FieldDescription[]`, `puckFieldsFromJsonSchema(schema: Record<string, unknown>): Fields`.
  - `src/client/frame-controller.ts`: `CHANGE_DEBOUNCE_MS = 600`, `class FrameController` (methods `announceReady`, `attachPuck`, `setShellFields`, `receive`, `componentSelected`, `componentDeselected`, `shellSelected`, `annotate`, `requestAsset`, `shortcut`, `linkClicked`, `pageEdited`, `flushChange`, `subscribe`, `getState`).
  - The page posts, in order: `ready` at boot; `navigated {route}` after each applied `init` and each page switch; `selected`/`deselected` for Puck's selection and the shell; `annotate` for a click on a section or the shell in edit mode; `changed {site}` 600 ms after the last edit (or at once on blur, a mode change, a page switch or a shortcut); `shortcut` for ⌘Z/⇧⌘Z outside editable text; `error {code: "section_load_failed"}` when a section does not load.

- [ ] **Step 1: Write the failing unit tests.**

`apps/frontend/packages/site-editor/test/boot.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { readBootContext } from "../src/client/boot";

test("the frame boots only with a well-formed nonce and an exact app origin", () => {
  const nonce = "2f6c1a9e-7b44-4c0e-9a21-3d5e8f0b1c2a";
  assert.deepEqual(readBootContext(`#n=${nonce}`, "http://localhost:3029"), { appOrigin: "http://localhost:3029", nonce });
  assert.equal(readBootContext("#n=short", "http://localhost:3029"), null);
  assert.equal(readBootContext("", "http://localhost:3029"), null);
  assert.equal(readBootContext(`#n=${nonce}`, null), null);
  assert.equal(readBootContext(`#n=${nonce}`, "http://localhost:3029/path"), null);
  assert.equal(readBootContext(`#n=${nonce}`, "%APP_ORIGIN%"), null);
});
```

`apps/frontend/packages/site-editor/test/sections.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { SectionLoadError, loadSections } from "../src/client/sections";

const DIGEST = "c".repeat(64);
const LINK = { digest: DIGEST, name: "AnalysisSteps", propsSchema: { type: "object" }, token: "tok_0123456789abcdef" };
const MODULE = { render: () => null, schema: { safeParse: () => ({ success: true }) } };

test("each section loads its module and stylesheet from this origin's token-checked route", async () => {
  const imported: string[] = [];
  const sheets: string[] = [];
  const loaded = await loadSections([LINK], {
    addStylesheet: (_digest, href) => sheets.push(href),
    importModule: async (url) => {
      imported.push(url);
      return MODULE;
    },
  });
  assert.deepEqual(imported, [`/sections/${DIGEST}.mjs?t=tok_0123456789abcdef`]);
  assert.deepEqual(sheets, [`/sections/${DIGEST}.css?t=tok_0123456789abcdef`]);
  assert.equal(loaded[0].name, "AnalysisSteps");
  assert.deepEqual(loaded[0].propsSchema, { type: "object" });
});

test("a module that fails to import, or exports no schema and render, fails the init with its name", async () => {
  await assert.rejects(
    loadSections([LINK], {
      addStylesheet: () => undefined,
      importModule: async () => {
        throw new TypeError("Failed to fetch dynamically imported module");
      },
    }),
    (error: unknown) => error instanceof SectionLoadError && error.sectionName === "AnalysisSteps",
  );
  await assert.rejects(
    loadSections([LINK], { addStylesheet: () => undefined, importModule: async () => ({ default: 1 }) }),
    SectionLoadError,
  );
});
```

`apps/frontend/packages/site-editor/test/fields.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { garner } from "../../site-kit/test/fixtures/garner";
import { buildPageConfig, shellFieldDescriptions } from "../src/client/config";
import { describeFields, fieldsForComponent, humanize, puckFieldsFromJsonSchema } from "../src/client/fields";

const brand = garner();
const config = buildPageConfig(brand, null, []);
const byName = <T extends { name: string }>(items: T[]) => Object.fromEntries(items.map((item) => [item.name, item]));

test("labels read like words", () => {
  assert.equal(humanize("buttonHref"), "Button href");
  assert.equal(humanize("cta_label"), "Cta label");
  assert.equal(humanize("AnalysisSteps"), "Analysis steps");
});

test("a built-in section describes its fields with the dock's kinds", () => {
  const fields = byName(fieldsForComponent(config, brand, "FeatureSplit", { id: "what" }));
  assert.equal(fields.heading.kind, "text");
  assert.equal(fields.body.kind, "textarea");
  assert.equal(fields.image.kind, "image");
  assert.equal(fields.buttonHref.kind, "link");
  assert.equal(fields.buttonHref.label, "Button link");
  assert.equal(fields.imageSide.kind, "select");
  assert.equal(fields.surface.kind, "select");
  assert.ok(fields.surface.options?.some((option) => option.label === "Brand" && option.value === "brand"));
});

test("a list field describes its items", () => {
  const fields = byName(fieldsForComponent(config, brand, "StatsBand", { id: "proof" }));
  assert.equal(fields.stats.kind, "list");
  assert.deepEqual(fields.stats.item?.map((item) => [item.name, item.kind]), [
    ["value", "text"],
    ["label", "textarea"],
  ]);
});

test("a cloned section shows its slots by name and kind, never the clone machinery", () => {
  const clone = Object.values(brand.clones)[0];
  const fields = fieldsForComponent(config, brand, "ClonedSection", { fragmentId: clone.id, id: "hero" });
  assert.ok(fields.length > 0);
  assert.ok(fields.every((field) => field.name.startsWith("slots.")));
  const slots = byName(fields);
  assert.deepEqual([slots["slots.headline"].kind, slots["slots.headline"].label], ["textarea", "Headline"]);
  assert.equal(slots["slots.cta_href"].kind, "link");
  assert.equal(slots["slots.visible"].kind, "boolean");
  assert.deepEqual(fieldsForComponent(config, brand, "ClonedSection", { fragmentId: "frag_missing", id: "x" }), []);
});

test("the header and footer describe their own fields", () => {
  const shell = shellFieldDescriptions(brand);
  const header = byName(shell.header);
  assert.equal(header.preparedFor.kind, "text");
  assert.equal(header.accountLogo.kind, "image");
  assert.equal(header.ctaHref.kind, "link");
  assert.deepEqual(header.nav.item?.map((item) => [item.name, item.kind]), [
    ["label", "text"],
    ["href", "link"],
  ]);
  assert.deepEqual(shell.footer.map((field) => [field.name, field.kind]), [
    ["legal", "text"],
    ["privacyHref", "link"],
    ["termsHref", "link"],
  ]);
});

test("an agent section's props schema becomes inline-editable Puck fields and dock fields", () => {
  const puck = puckFieldsFromJsonSchema({
    type: "object",
    properties: {
      id: { type: "string" },
      heading: { type: "string" },
      body: { type: "string" },
      ctaHref: { type: "string" },
      heroImage: { type: "string" },
      tone: { type: "string", enum: ["calm", "bold"] },
      featured: { type: "boolean" },
      count: { type: "integer" },
      steps: { type: "array", items: { type: "object", properties: { title: { type: "string" } } } },
      tags: { type: "array", items: { type: "string" } },
    },
  }) as Record<string, { type: string; contentEditable?: boolean }>;
  assert.equal("id" in puck, false);
  assert.deepEqual([puck.heading.type, puck.heading.contentEditable], ["text", true]);
  assert.deepEqual([puck.body.type, puck.body.contentEditable], ["textarea", true]);
  assert.deepEqual([puck.ctaHref.type, puck.ctaHref.contentEditable], ["text", false]);
  assert.equal(puck.heroImage.type, "custom");
  assert.equal("tags" in puck, false, "an array of plain strings has no dock control yet");
  const described = byName(describeFields(puck as never));
  assert.deepEqual(
    ["heading", "body", "ctaHref", "heroImage", "tone", "featured", "count", "steps"].map((name) => described[name].kind),
    ["text", "textarea", "link", "image", "select", "boolean", "number", "list"],
  );
});
```

`apps/frontend/packages/site-editor/test/dom.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { clickIntent, rectOf } from "../src/client/dom";

const dom = new JSDOM(`
  <div class="brand-root">
    <header><a id="nav" href="/analysis">Analysis</a></header>
    <div data-puck-component="proof"><h2 id="heading">Stats</h2><a id="cta" href="https://garnerhealth.com">Go</a></div>
    <a id="anchor" href="#top">Top</a>
    <footer><span id="legal">©</span></footer>
  </div>`);
const byId = (id: string) => dom.window.document.getElementById(id);

function summary(intent: ReturnType<typeof clickIntent>) {
  const { action, preventDefault } = intent;
  if (action.kind === "navigate") return { href: action.href, kind: action.kind, preventDefault };
  if (action.kind === "shell") return { kind: action.kind, part: action.part, preventDefault };
  if (action.kind === "component") return { componentId: action.componentId, kind: action.kind, preventDefault };
  return { kind: action.kind, preventDefault };
}

test("preview mode follows links and leaves in-page anchors to the browser", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "preview")), { href: "/analysis", kind: "navigate", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("cta"), "preview")), {
    href: "https://garnerhealth.com",
    kind: "navigate",
    preventDefault: true,
  });
  assert.deepEqual(summary(clickIntent(byId("anchor"), "preview")), { kind: "none", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "preview")), { kind: "none", preventDefault: false });
});

test("edit mode selects the header, the footer or a section, and never follows a link", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "edit")), { kind: "shell", part: "header", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("legal"), "edit")), { kind: "shell", part: "footer", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "edit")), { componentId: "proof", kind: "component", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("cta"), "edit")), { componentId: "proof", kind: "component", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("heading")?.firstChild ?? null, "edit")), {
    componentId: "proof",
    kind: "component",
    preventDefault: false,
  });
});

test("geometry is the element's box in viewport and document coordinates", () => {
  const element = { getBoundingClientRect: () => ({ bottom: 60, height: 50, left: 5, right: 105, top: 10, width: 100, x: 5, y: 10 }) };
  const geometry = rectOf(element as unknown as Element, { x: 0, y: 400 });
  assert.equal(geometry.viewport.top, 10);
  assert.equal(geometry.document.top, 410);
  assert.equal(geometry.document.y, 410);
  assert.equal(geometry.document.left, 5);
});
```

`apps/frontend/packages/site-editor/test/frame-controller.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { appToFrame, type FrameToAppType } from "@clue/site-kit/editor-protocol";
import { SiteDocumentSchema, type SitePage } from "@clue/site-kit/site-document";
import { FrameController, type PuckHandle } from "../src/client/frame-controller";
import type { LoadedSection } from "../src/client/sections";

const NONCE = "nonce-0123456789abcdef";
const brand = { slug: "x", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } as unknown as BrandData;
const page = (heading: string): SitePage => ({
  root: { props: { title: "Home" } },
  content: [{ type: "CtaBand", props: { id: "cta", heading } }],
});
const site = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "S",
  theme: {},
  pages: { "/": page("Hello"), "/analysis": { root: { props: { title: "Analysis" } }, content: [] } },
  shell: { header: { id: "header", preparedFor: "SCSD" }, footer: { id: "footer", legal: "©" } },
  agent_sections: {},
});
const init = (overrides: Record<string, unknown> = {}) =>
  appToFrame(
    "init",
    { brand, device: "Desktop", mode: "edit", route: "/", sections: [], site, ...overrides } as never,
    { documentId: "doc_1", nonce: NONCE },
  );

function harness(loadSections: () => Promise<LoadedSection[]> = async () => []) {
  const posts: { type: FrameToAppType; payload: unknown; documentId: string }[] = [];
  const timers: (() => void)[] = [];
  const puckCalls: string[] = [];
  const controller = new FrameController({
    cancel: () => undefined,
    loadSections,
    post: (type, payload, documentId) => posts.push({ documentId, payload, type }),
    schedule: (run) => {
      timers.push(run);
      return timers.length;
    },
  });
  const puck: PuckHandle = {
    select: (id) => puckCalls.push(`select:${id}`),
    setMode: (mode) => puckCalls.push(`mode:${mode}`),
    showPage: (shown) => puckCalls.push(`show:${String(shown.content[0]?.props.heading ?? "")}`),
  };
  controller.attachPuck(puck);
  controller.setShellFields({ footer: [{ kind: "text", label: "Legal", name: "legal" }], header: [{ kind: "text", label: "Prepared for", name: "preparedFor" }] });
  const types = () => posts.map((post) => post.type);
  return { controller, posts, puckCalls, timers, types };
}

test("boot says ready with no document; init loads, renders and says navigated for that document", async () => {
  const h = harness();
  h.controller.announceReady();
  await h.controller.receive(init());
  assert.deepEqual(h.types(), ["ready", "navigated"]);
  assert.equal(h.posts[0].documentId, "");
  assert.equal(h.posts[1].documentId, "doc_1");
  assert.equal(h.controller.getState().status, "ready");
  assert.equal(h.controller.getState().route, "/");
});

test("an init whose route is not a page falls back to the home page", async () => {
  const h = harness();
  await h.controller.receive(init({ route: "/gone" }));
  assert.deepEqual(h.posts.at(-1), { documentId: "doc_1", payload: { route: "/" }, type: "navigated" });
});

test("a section that does not load fails the init with a typed error", async () => {
  const h = harness(async () => {
    throw new Error("AnalysisSteps did not load");
  });
  await h.controller.receive(init());
  assert.equal(h.controller.getState().status, "failed");
  assert.deepEqual(h.posts.at(-1)?.payload, { code: "section_load_failed", message: "AnalysisSteps did not load" });
});

test("a user edit is posted once, after the debounce, with the whole site", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Edited once"));
  h.controller.pageEdited("/", page("Edited twice"));
  assert.equal(h.types().includes("changed"), false);
  h.timers.at(-1)?.();
  const changed = h.posts.filter((post) => post.type === "changed");
  assert.equal(changed.length, 1);
  const sent = (changed[0].payload as { site: typeof site }).site;
  assert.equal(sent.pages["/"].content[0].props.heading, "Edited twice");
  assert.equal(sent.pages["/analysis"].root.props.title, "Analysis", "the other pages ride along unchanged");
});

test("an echo of the page as it already is posts nothing; preview mode never posts edits", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Hello"));
  assert.equal(h.timers.length, 0);
  await h.controller.receive(appToFrame("set_mode", { mode: "preview" }, { documentId: "doc_1", nonce: NONCE }));
  h.controller.pageEdited("/", page("Typed in preview"));
  assert.equal(h.timers.length, 0);
});

test("leaving edit mode, switching page or a shortcut flushes a pending edit first", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Pending"));
  h.controller.shortcut("undo");
  assert.deepEqual(h.types().slice(-2), ["changed", "shortcut"]);
});

test("the app's own edits re-render the page without echoing a change back", async () => {
  const h = harness();
  await h.controller.receive(init());
  await h.controller.receive(
    appToFrame("set_props", { componentId: "cta", props: { heading: "From the dock" }, route: "/" }, { documentId: "doc_1", nonce: NONCE }),
  );
  assert.deepEqual(h.puckCalls.at(-1), "show:From the dock");
  h.controller.pageEdited("/", h.controller.getState().site!.pages["/"]);
  assert.equal(h.types().includes("changed"), false);
});

test("an agent reload replaces the site, drops an unsent edit, and keeps the page", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.pageEdited("/", page("Unsent"));
  const agent = { ...site, pages: { ...site.pages, "/": page("Agent wrote this") } };
  await h.controller.receive(appToFrame("replace_site", { site: agent, version: 9 }, { documentId: "doc_1", nonce: NONCE }));
  h.timers.forEach((run) => run());
  assert.equal(h.types().includes("changed"), false, "the server's version wins over an unsent edit");
  assert.equal(h.puckCalls.at(-1), "show:Agent wrote this");
});

test("the header is selected through the shell target with its own fields", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.shellSelected("header");
  assert.deepEqual(h.posts.at(-1)?.payload, {
    componentId: "header",
    componentType: "SiteHeader",
    fields: [{ kind: "text", label: "Prepared for", name: "preparedFor" }],
    props: { id: "header", preparedFor: "SCSD" },
    route: "shell",
  });
  h.controller.componentDeselected();
  assert.equal(h.types().at(-1), "selected", "Puck clearing its own selection does not clear the shell's");
});

test("a site link in preview switches page; an outside link does nothing", async () => {
  const h = harness();
  await h.controller.receive(init({ mode: "preview" }));
  h.controller.linkClicked("https://garnerhealth.com");
  assert.equal(h.types().at(-1), "navigated");
  assert.equal(h.posts.filter((post) => post.type === "navigated").length, 1);
  h.controller.linkClicked("/analysis");
  assert.deepEqual(h.posts.at(-1)?.payload, { route: "/analysis" });
  assert.equal(h.controller.getState().route, "/analysis");
});
```

`apps/frontend/packages/site-editor/test/build.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { IMPORT_MAP, compileStyles, pageHtml, shimSource } from "../scripts/build";

test("the stylesheet carries the brand-token utilities site-kit's sections use, and Puck's own styles", async () => {
  const css = await compileStyles();
  for (const utility of [".bg-surface-page", ".bg-surface-brand-subtle", ".font-headline", ".text-headline", ".rounded-card", ".text-ink-inverse"]) {
    assert.ok(css.includes(utility), utility);
  }
  assert.ok(css.includes("--puck-color-azure-04"), "Puck's stylesheet is bundled");
  assert.ok(css.includes("[data-site-shell-selected]"));
});

test("each shim re-exports the editor's own copy and fails loudly before it is shared", () => {
  const source = shimSource("react", ["useState", "useEffect"]);
  assert.ok(source.includes('globalThis.__clueSectionHost["react"]'));
  assert.ok(source.includes("export const { useState, useEffect } = m;"));
  assert.ok(source.includes("throw new Error"));
});

test("the page has exactly one inline script — the nonced import map — and the bundle", () => {
  const html = pageHtml("editor-1.js", "editor-1.css");
  assert.equal(html.match(/<script/g)?.length, 2);
  assert.ok(html.includes(`<script type="importmap" nonce="%NONCE%">${IMPORT_MAP}</script>`));
  assert.ok(html.includes('<script type="module" src="/assets/editor-1.js"></script>'));
  assert.ok(html.includes('<meta name="clue-app-origin" content="%APP_ORIGIN%">'));
  assert.deepEqual(JSON.parse(IMPORT_MAP).imports, {
    react: "/shims/react.mjs",
    "react/jsx-runtime": "/shims/react-jsx-runtime.mjs",
    zod: "/shims/zod.mjs",
  });
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npm test -w @clue/site-editor 2>&1 | tail -5`
Expected: FAIL — `Cannot find module '../src/client/boot'` (and the other new modules).

- [ ] **Step 3: Write the small client modules.**

`apps/frontend/packages/site-editor/src/client/jitless.ts`:
```ts
// zod 4 probes `new Function` to decide whether it may compile fast parsers. The editor's policy
// has no 'unsafe-eval', so the probe would raise a violation: jitless turns it off. main.tsx imports
// this module FIRST, before any other module can parse a schema.
import { z } from "zod";

z.config({ jitless: true });
```

`apps/frontend/packages/site-editor/src/client/host-globals.ts`:
```ts
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as zod from "zod";

declare global {
  // eslint-disable-next-line no-var
  var __clueSectionHost: Record<string, unknown> | undefined;
}

/** A compiled agent section keeps three imports: react, react/jsx-runtime and zod. The page's import
 * map points each at a shim on this origin (/shims/*.mjs) that re-exports the copy put here, so a
 * section runs on the editor's one React (hooks and context work) and the editor's zod. */
export function installSectionHost(): void {
  globalThis.__clueSectionHost = { react: React, "react/jsx-runtime": jsxRuntime, zod };
}
```

`apps/frontend/packages/site-editor/src/client/boot.ts`:
```ts
export interface BootContext {
  appOrigin: string;
  nonce: string;
}

const NONCE = /^[A-Za-z0-9_-]{16,128}$/;

/** The frame's two boot facts: the nonce the app put in the URL fragment (`#n=<nonce>`, never sent
 * to a server) and the app origin the server wrote into the page. Anything malformed → no boot. */
export function readBootContext(hash: string, appOriginMeta: string | null): BootContext | null {
  const nonce = new URLSearchParams(hash.replace(/^#/, "")).get("n") ?? "";
  if (!NONCE.test(nonce) || !appOriginMeta) return null;
  let parsed: URL;
  try {
    parsed = new URL(appOriginMeta);
  } catch {
    return null;
  }
  if (parsed.origin !== appOriginMeta) return null;
  return { appOrigin: parsed.origin, nonce };
}
```

`apps/frontend/packages/site-editor/src/client/sections.ts`:
```ts
import type { AgentSectionModule } from "@clue/site-kit";
import type { SectionLink } from "@clue/site-kit/site-document";

export interface LoadedSection {
  digest: string;
  module: AgentSectionModule;
  name: string;
  propsSchema: Record<string, unknown>;
}

export class SectionLoadError extends Error {
  readonly sectionName: string;

  constructor(sectionName: string, reason: string) {
    super(`The section ${sectionName} could not be loaded: ${reason}`);
    this.name = "SectionLoadError";
    this.sectionName = sectionName;
  }
}

export const sectionModuleUrl = (link: SectionLink) => `/sections/${link.digest}.mjs?t=${encodeURIComponent(link.token)}`;
export const sectionStyleUrl = (link: SectionLink) => `/sections/${link.digest}.css?t=${encodeURIComponent(link.token)}`;

export function isSectionModule(value: unknown): value is AgentSectionModule {
  const candidate = value as { render?: unknown; schema?: { safeParse?: unknown } } | null;
  return typeof candidate?.render === "function" && typeof candidate?.schema?.safeParse === "function";
}

export interface SectionLoaderDeps {
  addStylesheet: (digest: string, href: string) => void;
  importModule: (url: string) => Promise<unknown>;
}

/** Contract 4: every section comes from THIS origin's token-checked route (Task 5). One failure
 * fails the whole init, named, so the app shows the canvas error instead of a half page. */
export async function loadSections(links: readonly SectionLink[], deps: SectionLoaderDeps): Promise<LoadedSection[]> {
  return Promise.all(
    links.map(async (link) => {
      deps.addStylesheet(link.digest, sectionStyleUrl(link));
      let module: unknown;
      try {
        module = await deps.importModule(sectionModuleUrl(link));
      } catch (cause) {
        throw new SectionLoadError(link.name, cause instanceof Error ? cause.message : String(cause));
      }
      if (!isSectionModule(module)) throw new SectionLoadError(link.name, "it exports no schema and render");
      return { digest: link.digest, module, name: link.name, propsSchema: link.propsSchema };
    }),
  );
}

export function browserSectionDeps(): SectionLoaderDeps {
  return {
    addStylesheet(digest, href) {
      if (document.head.querySelector(`link[data-section-digest="${digest}"]`)) return;
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.sectionDigest = digest;
      document.head.appendChild(link);
    },
    // A runtime URL, deliberately not bundled: esbuild leaves a non-literal import() alone.
    importModule: (url) => import(/* webpackIgnore: true */ url),
  };
}
```

`apps/frontend/packages/site-editor/src/client/fields.ts`:
```ts
import type { Config, Field, Fields } from "@puckeditor/core";
import type { BrandData } from "@clue/site-kit";
import type { FieldDescription, FieldKind, FieldOption } from "@clue/site-kit/editor-protocol";

/**
 * Contract 6's FieldDescription, derived in the frame (where the Puck config lives) and drawn in
 * the app's dock. Built-in sections describe their site-kit Puck fields; a cloned section shows its
 * slots (never the clone id, text replacements or link replacements — the marketer never sees
 * "clones"); an agent section's fields come from its props JSON Schema (the D2 spike's `fieldsFrom`,
 * `trials/puck-spike/app/edit-runtime/[site]/client.tsx:41-69`).
 */
const LINK_NAME = /(href|link|url)$/i;
const IMAGE_NAME = /(image|logo|photo|picture|src)$/i;
const LONG_TEXT = /(body|intro|statement|description|quote|summary)$/i;
const SLOT_KINDS: Record<string, FieldKind> = { href: "link", image: "image", text: "textarea", visibility: "boolean" };
const HIDDEN: Record<string, readonly string[]> = { ClonedSection: ["fragmentId", "slots", "replacements", "links"] };

type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
};

export function humanize(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const isOptionValue = (value: unknown): value is FieldOption["value"] =>
  typeof value === "string" || typeof value === "number" || typeof value === "boolean";

function describeField(name: string, field: Field): FieldDescription[] {
  const label = field.label ?? humanize(name);
  switch (field.type) {
    case "text":
      return [{ kind: IMAGE_NAME.test(name) ? "image" : LINK_NAME.test(name) ? "link" : "text", label, name }];
    case "textarea":
      return [{ kind: "textarea", label, name }];
    case "number":
      return [{ kind: "number", label, name }];
    case "select":
    case "radio": {
      const options = field.options
        .filter((option) => isOptionValue(option.value))
        .map((option) => ({ label: String(option.label), value: option.value as FieldOption["value"] }));
      const boolean = options.length === 2 && options.every((option) => typeof option.value === "boolean");
      return [boolean ? { kind: "boolean", label, name } : { kind: "select", label, name, options }];
    }
    case "custom":
      return [{ kind: "image", label, name }];
    case "array":
      return [{ item: describeFields(field.arrayFields as Fields), kind: "list", label, name }];
    case "object":
      return describeFields(field.objectFields as Fields).map((child) => ({ ...child, name: `${name}.${child.name}` }));
    default:
      return [];
  }
}

export function describeFields(fields: Fields, hidden: readonly string[] = []): FieldDescription[] {
  return Object.entries(fields).flatMap(([name, field]) => (hidden.includes(name) ? [] : describeField(name, field as Field)));
}

export function clonedSectionFields(brand: BrandData, props: Record<string, unknown>): FieldDescription[] {
  const clone = brand.clones[String(props.fragmentId ?? "")];
  if (!clone) return [];
  return Object.entries(clone.slots).flatMap(([key, slot]) => {
    const kind = SLOT_KINDS[slot.kind];
    return kind ? [{ kind, label: humanize(key), name: `slots.${key}` }] : [];
  });
}

export function fieldsForComponent(
  config: Config,
  brand: BrandData,
  type: string,
  props: Record<string, unknown>,
): FieldDescription[] {
  if (type === "ClonedSection") return clonedSectionFields(brand, props);
  const component = (config.components as Record<string, { fields?: Fields } | undefined>)[type];
  return describeFields(component?.fields ?? {}, HIDDEN[type] ?? []);
}

/** Puck fields for an agent section, from its props JSON Schema. Prose edits in place on the
 * canvas; links and images do not (they are edited in the dock). */
export function puckFieldsFromJsonSchema(schema: Record<string, unknown>): Fields {
  const fields: Record<string, Field> = {};
  const properties = (schema as JsonSchema).properties ?? {};
  for (const [key, property] of Object.entries(properties)) {
    if (key === "id") continue;
    const type = Array.isArray(property.type) ? property.type.find((entry) => entry !== "null") : property.type;
    const label = humanize(key);
    if (property.enum) {
      fields[key] = {
        label,
        options: property.enum.filter(isOptionValue).map((value) => ({ label: String(value), value })),
        type: "select",
      };
    } else if (type === "string" && IMAGE_NAME.test(key)) {
      fields[key] = { label, render: () => null, type: "custom" } as Field;
    } else if (type === "string") {
      fields[key] = {
        contentEditable: !LINK_NAME.test(key),
        label,
        type: LONG_TEXT.test(key) ? "textarea" : "text",
      };
    } else if (type === "boolean") {
      fields[key] = { label, options: [{ label: "Yes", value: true }, { label: "No", value: false }], type: "radio" };
    } else if (type === "number" || type === "integer") {
      fields[key] = { label, type: "number" };
    } else if (type === "array" && property.items?.type === "object") {
      fields[key] = { arrayFields: puckFieldsFromJsonSchema(property.items as Record<string, unknown>), label, type: "array" } as Field;
    } else if (type === "object") {
      fields[key] = { label, objectFields: puckFieldsFromJsonSchema(property as Record<string, unknown>), type: "object" } as Field;
    }
  }
  return fields as Fields;
}
```

`apps/frontend/packages/site-editor/src/client/config.tsx`:
```tsx
import { Component, type ReactNode } from "react";
import type { Config, Fields } from "@puckeditor/core";
import { makeConfig, type BrandData, type ShellData } from "@clue/site-kit";
import { AssetPicker, CloneEditor } from "@clue/site-kit/editor";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import type { SiteShell } from "@clue/site-kit/site-document";
import { describeFields, puckFieldsFromJsonSchema } from "./fields";
import type { LoadedSection } from "./sections";

type RenderFn = (props: Record<string, unknown>) => ReactNode;
type MutableConfig = Config & { components: Record<string, { fields?: Fields; render?: RenderFn }> };

/** A broken agent section — one that throws while rendering, for example because the editor's
 * policy refused something it tried — is left out on its own. It never takes the rest of the page,
 * or the editor, down with it (an uncaught render error unmounts a whole React root). */
class SectionBoundary extends Component<{ children: ReactNode; name: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    return this.state.failed ? <div data-agent-section-failed={this.props.name} /> : this.props.children;
  }
}

/** Calls the section's render INSIDE the boundary (a render function called outside it would throw
 * past it). */
function GuardedRender({ props, render }: { props: Record<string, unknown>; render: RenderFn }) {
  return <>{render(props)}</>;
}

/** The page config: site-kit's sections, the seller's clones, the shell drawn around every page,
 * and this site's agent sections with fields from their own props schema, each behind its own
 * error boundary. No basePath: internal links stay "/analysis", and the editor intercepts them and
 * switches pages itself. */
export function buildPageConfig(brand: BrandData, shell: SiteShell | null, sections: readonly LoadedSection[]): Config {
  const config = makeConfig(brand, {
    agentSections: Object.fromEntries(sections.map((section) => [section.name, section.module])),
    editor: { AssetPicker, CloneEditor },
    mode: "page",
    shell: (shell ?? undefined) as ShellData | undefined,
  }) as MutableConfig;
  for (const section of sections) {
    const component = config.components[section.name];
    if (!component) continue;
    component.fields = puckFieldsFromJsonSchema(section.propsSchema);
    const render = component.render;
    if (render) {
      component.render = (props) => (
        <SectionBoundary name={section.name}>
          <GuardedRender props={props} render={render} />
        </SectionBoundary>
      );
    }
  }
  return config;
}

/** The header's and footer's fields, from site-kit's shell config. */
export function shellFieldDescriptions(brand: BrandData): { footer: FieldDescription[]; header: FieldDescription[] } {
  const config = makeConfig(brand, { mode: "shell" }) as MutableConfig;
  return {
    footer: describeFields(config.components.SiteFooter?.fields ?? {}),
    header: describeFields(config.components.SiteHeader?.fields ?? {}),
  };
}
```

`apps/frontend/packages/site-editor/src/client/dom.ts`:
```ts
import type { EditorMode, SiteGeometry } from "@clue/site-kit/editor-protocol";

export type ClickAction =
  | { kind: "navigate"; href: string }
  | { kind: "shell"; part: "header" | "footer"; element: Element }
  | { kind: "component"; componentId: string; element: Element }
  | { kind: "none" };

function asElement(target: EventTarget | null): Element | null {
  const node = target as (Partial<Element> & { parentElement?: Element | null }) | null;
  if (!node) return null;
  if (typeof node.closest === "function") return node as Element;
  return node.parentElement ?? null; // a text node
}

/**
 * What one click on the canvas means. Preview: a link switches page (the frame never navigates
 * itself — `preventDefault` — except to an in-page "#anchor"). Edit: a click on the header/footer
 * selects the shell, a click on a section reports it for the comment box, and no link is followed.
 */
export function clickIntent(target: EventTarget | null, mode: EditorMode): { action: ClickAction; preventDefault: boolean } {
  const element = asElement(target);
  if (!element) return { action: { kind: "none" }, preventDefault: false };
  const anchor = element.closest("a[href]");
  const href = anchor?.getAttribute("href") ?? null;
  const inPage = href !== null && href.startsWith("#");
  const preventDefault = anchor !== null && (mode === "edit" || !inPage);
  if (mode !== "edit") {
    return { action: href !== null && !inPage ? { href, kind: "navigate" } : { kind: "none" }, preventDefault };
  }
  const shell = element.closest(".brand-root > header, .brand-root > footer");
  if (shell) {
    return {
      action: { element: shell, kind: "shell", part: shell.tagName.toLowerCase() === "header" ? "header" : "footer" },
      preventDefault,
    };
  }
  const component = element.closest("[data-puck-component]");
  if (component) {
    return {
      action: { componentId: component.getAttribute("data-puck-component") ?? "", element: component, kind: "component" },
      preventDefault,
    };
  }
  return { action: { kind: "none" }, preventDefault };
}

/** The web bridge's geometry shape: the element's box in viewport and in document coordinates. */
export function rectOf(element: Element, scroll: { x: number; y: number }): SiteGeometry {
  const box = element.getBoundingClientRect();
  const viewport = {
    bottom: box.bottom,
    height: box.height,
    left: box.left,
    right: box.right,
    top: box.top,
    width: box.width,
    x: box.x,
    y: box.y,
  };
  return {
    document: {
      ...viewport,
      bottom: box.bottom + scroll.y,
      left: box.left + scroll.x,
      right: box.right + scroll.x,
      top: box.top + scroll.y,
      x: box.x + scroll.x,
      y: box.y + scroll.y,
    },
    viewport,
  };
}
```

- [ ] **Step 4: Write the frame controller.**

`apps/frontend/packages/site-editor/src/client/frame-controller.ts`:
```ts
import type { BrandData } from "@clue/site-kit";
import type {
  AppToFrameMessage,
  AppToFramePayloads,
  EditorMode,
  FieldDescription,
  FrameToAppPayloads,
  FrameToAppType,
  SiteGeometry,
} from "@clue/site-kit/editor-protocol";
import {
  canonicalJson,
  componentProps,
  internalRoute,
  pageFor,
  withAssetAt,
  withComponentProps,
  withPage,
} from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SectionLink, type SiteDocument, type SitePage, type SiteTarget } from "@clue/site-kit/site-document";
import type { LoadedSection } from "./sections";

/** The pause after the last keystroke before an edit is sent (blur, a mode change, a page switch
 * and a shortcut send it at once). Each send is one save, and one save is one undo step. */
export const CHANGE_DEBOUNCE_MS = 600;

export type FrameStatus = "booting" | "loading" | "ready" | "failed";

export interface FrameSelection {
  componentId: string;
  target: SiteTarget;
}

export interface FrameState {
  brand: BrandData | null;
  documentId: string;
  mode: EditorMode;
  /** Bumps whenever Puck must remount: a new document, another page. */
  mountKey: number;
  route: string;
  sections: LoadedSection[];
  selection: FrameSelection | null;
  site: SiteDocument | null;
  status: FrameStatus;
}

/** What the controller may ask of the mounted Puck (wired by editor-app.tsx's PuckBridge). */
export interface PuckHandle {
  select(componentId: string | null): void;
  setMode(mode: EditorMode): void;
  showPage(page: SitePage): void;
}

export type FramePost = <T extends FrameToAppType>(type: T, payload: FrameToAppPayloads[T], documentId: string) => void;

export interface FrameControllerDeps {
  cancel?: (handle: unknown) => void;
  loadSections: (links: readonly SectionLink[]) => Promise<LoadedSection[]>;
  post: FramePost;
  schedule?: (run: () => void, ms: number) => unknown;
}

export interface ShellFields {
  footer: FieldDescription[];
  header: FieldDescription[];
}

const INITIAL: FrameState = {
  brand: null,
  documentId: "",
  mode: "preview",
  mountKey: 0,
  route: "/",
  sections: [],
  selection: null,
  site: null,
  status: "booting",
};

export class FrameController {
  private state: FrameState = INITIAL;
  private readonly listeners = new Set<() => void>();
  private puck: PuckHandle | null = null;
  private shellFields: ShellFields | null = null;
  private timer: unknown = null;
  private changePending = false;
  private initGeneration = 0;

  constructor(private readonly deps: FrameControllerDeps) {}

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getState = (): FrameState => this.state;

  announceReady(): void {
    this.deps.post("ready", {}, "");
  }

  attachPuck(handle: PuckHandle | null): void {
    this.puck = handle;
  }

  setShellFields(fields: ShellFields | null): void {
    this.shellFields = fields;
  }

  async receive(message: AppToFrameMessage): Promise<void> {
    switch (message.type) {
      case "init":
        return this.init(message.documentId, message.payload);
      case "replace_site":
        return this.replaceSite(message.payload.site);
      case "set_mode":
        return this.setMode(message.payload.mode);
      case "navigate":
        return this.navigate(message.payload.route);
      case "select":
        return this.select(message.payload.route, message.payload.componentId);
      case "set_props": {
        const { componentId, props, route } = message.payload;
        if (this.state.site) this.applyOutsideEdit(withComponentProps(this.state.site, route, componentId, props), route);
        return;
      }
      case "insert_asset": {
        const { componentId, prop, route, url } = message.payload;
        if (this.state.site) this.applyOutsideEdit(withAssetAt(this.state.site, route, componentId, prop, url), route);
        return;
      }
    }
  }

  /** Puck reports a page section as selected (a click on the canvas, or the app's `select`). */
  componentSelected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void {
    if (this.state.mode !== "edit") return;
    const current = this.state.selection;
    if (current && current.target === this.state.route && current.componentId === componentId) return;
    this.set({ selection: { componentId, target: this.state.route } });
    this.post("selected", { componentId, componentType, fields, props, route: this.state.route });
  }

  /** Puck reports nothing selected. The shell's selection is not Puck's to clear. */
  componentDeselected(): void {
    const current = this.state.selection;
    if (!current || current.target === SHELL_TARGET) return;
    this.set({ selection: null });
    this.post("deselected", {});
  }

  shellSelected(part: "header" | "footer"): void {
    const site = this.state.site;
    if (this.state.mode !== "edit" || !site?.shell || !this.shellFields) return;
    this.puck?.select(null);
    this.set({ selection: { componentId: part, target: SHELL_TARGET } });
    this.post("selected", {
      componentId: part,
      componentType: part === "header" ? "SiteHeader" : "SiteFooter",
      fields: this.shellFields[part],
      props: site.shell[part],
      route: SHELL_TARGET,
    });
  }

  annotate(target: SiteTarget, componentId: string, geometry: SiteGeometry): void {
    if (this.state.mode !== "edit") return;
    this.post("annotate", { componentId, geometry, route: target });
  }

  requestAsset(target: SiteTarget, componentId: string, prop: string): void {
    if (this.state.mode !== "edit") return;
    this.post("request_asset", { componentId, prop, route: target });
  }

  shortcut(action: "undo" | "redo"): void {
    this.flushChange();
    this.post("shortcut", { action });
  }

  linkClicked(href: string): void {
    const site = this.state.site;
    if (!site) return;
    const route = internalRoute(href, site);
    if (route) this.navigate(route);
  }

  /** Puck's onChange: the user edited the page shown. An echo of the page as stored is ignored. */
  pageEdited(route: string, page: SitePage): void {
    const site = this.state.site;
    if (!site || this.state.mode !== "edit" || route !== this.state.route) return;
    const current = pageFor(site, route);
    if (current && canonicalJson(withoutEmptyZones(current)) === canonicalJson(withoutEmptyZones(page))) return;
    this.set({ site: withPage(site, route, page) });
    this.scheduleChange();
  }

  flushChange(): void {
    if (!this.changePending) return;
    this.cancelChange();
    if (this.state.site) this.post("changed", { site: this.state.site });
  }

  private async init(documentId: string, payload: AppToFramePayloads["init"]): Promise<void> {
    const generation = ++this.initGeneration;
    this.cancelChange();
    this.set({ brand: null, documentId, mode: payload.mode, sections: [], selection: null, site: null, status: "loading" });
    let sections: LoadedSection[];
    try {
      sections = await this.deps.loadSections(payload.sections);
    } catch (error) {
      if (generation !== this.initGeneration) return;
      this.set({ status: "failed" });
      this.post("error", { code: "section_load_failed", message: error instanceof Error ? error.message : String(error) });
      return;
    }
    if (generation !== this.initGeneration) return;
    const route = pageFor(payload.site, payload.route) ? payload.route : "/";
    this.set({ brand: payload.brand, mountKey: this.state.mountKey + 1, route, sections, site: payload.site, status: "ready" });
    this.post("navigated", { route });
  }

  private replaceSite(site: SiteDocument): void {
    if (!this.state.site) return;
    // The server's version wins over an unsent edit, exactly as the web lane's 409 drops one.
    this.cancelChange();
    const route = pageFor(site, this.state.route) ? this.state.route : "/";
    const previous = this.state.selection;
    const selection = previous && componentProps(site, previous.target, previous.componentId) ? previous : null;
    if (route !== this.state.route) {
      this.set({ mountKey: this.state.mountKey + 1, route, selection, site });
      this.post("navigated", { route });
    } else {
      this.set({ selection, site });
      const page = pageFor(site, route);
      if (page) this.puck?.showPage(page);
    }
    if (previous && !selection) this.post("deselected", {});
  }

  private setMode(mode: EditorMode): void {
    if (mode === this.state.mode) return;
    if (this.state.mode === "edit") this.flushChange();
    const hadSelection = this.state.selection !== null;
    this.set({ mode, selection: mode === "edit" ? this.state.selection : null });
    this.puck?.setMode(mode);
    if (mode !== "edit" && hadSelection) this.post("deselected", {});
  }

  private navigate(route: string): void {
    const site = this.state.site;
    if (!site || !pageFor(site, route)) return;
    if (route === this.state.route) {
      this.post("navigated", { route });
      return;
    }
    this.flushChange();
    const hadSelection = this.state.selection !== null;
    this.set({ mountKey: this.state.mountKey + 1, route, selection: null });
    this.post("navigated", { route });
    if (hadSelection) this.post("deselected", {});
  }

  private select(target: SiteTarget, componentId: string | null): void {
    if (this.state.mode !== "edit" || !this.state.site) return;
    if (componentId === null) {
      this.puck?.select(null);
      if (this.state.selection) {
        this.set({ selection: null });
        this.post("deselected", {});
      }
      return;
    }
    if (target === SHELL_TARGET) {
      if (componentId === "header" || componentId === "footer") this.shellSelected(componentId);
      return;
    }
    if (target === this.state.route) this.puck?.select(componentId);
  }

  private applyOutsideEdit(site: SiteDocument, target: SiteTarget): void {
    if (site === this.state.site) return;
    this.set({ site });
    if (target === this.state.route) {
      const page = pageFor(site, target);
      if (page) this.puck?.showPage(page);
    }
  }

  private scheduleChange(): void {
    this.cancelTimer();
    this.changePending = true;
    const schedule = this.deps.schedule ?? ((run: () => void, ms: number) => setTimeout(run, ms));
    this.timer = schedule(() => this.flushChange(), CHANGE_DEBOUNCE_MS);
  }

  private cancelTimer(): void {
    if (this.timer === null) return;
    (this.deps.cancel ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>)))(this.timer);
    this.timer = null;
  }

  private cancelChange(): void {
    this.cancelTimer();
    this.changePending = false;
  }

  private post<T extends FrameToAppType>(type: T, payload: FrameToAppPayloads[T]): void {
    this.deps.post(type, payload, this.state.documentId);
  }

  private set(patch: Partial<FrameState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}

/** Puck reports `zones: {}` for a page stored without zones; the two are the same page. */
function withoutEmptyZones(page: SitePage): SitePage {
  if (page.zones && Object.keys(page.zones).length === 0) {
    const copy = { ...page };
    delete copy.zones;
    return copy;
  }
  return page;
}
```

- [ ] **Step 5: Write the React layer and the entry.**

`apps/frontend/packages/site-editor/src/client/editor-app.tsx`:
```tsx
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { Puck, createUsePuck, useGetPuck, type Config, type Data, type Permissions, type Viewports } from "@puckeditor/core";
import type { BrandData } from "@clue/site-kit";
import { acceptAppMessage, frameToApp } from "@clue/site-kit/editor-protocol";
import { canonicalJson, pageFor, shortcutFor } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SitePage, type SiteShell } from "@clue/site-kit/site-document";
import type { BootContext } from "./boot";
import { buildPageConfig, shellFieldDescriptions } from "./config";
import { clickIntent, rectOf } from "./dom";
import { fieldsForComponent } from "./fields";
import { FrameController } from "./frame-controller";
import { browserSectionDeps, loadSections } from "./sections";

const usePuck = createUsePuck();
// Insert, delete, duplicate and drag wait for the founder's designs (C13); in-place editing stays on.
const PERMISSIONS: Partial<Permissions> = { delete: false, drag: false, duplicate: false, edit: true, insert: false };
const VIEWPORTS: Viewports = [{ height: "auto", label: "Page", width: "100%" }];
const SHELL_SELECTED = "data-site-shell-selected";

export function EditorApp({ boot }: { boot: BootContext }) {
  const controller = useMemo(
    () =>
      new FrameController({
        loadSections: (links) => loadSections(links, browserSectionDeps()),
        post: (type, payload, documentId) => {
          // Contract 6: always the app's exact origin, never "*".
          window.parent.postMessage(frameToApp(type, payload, { documentId, nonce: boot.nonce }), boot.appOrigin);
        },
      }),
    [boot],
  );
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = acceptAppMessage(
        { data: event.data, origin: event.origin, source: event.source },
        { appOrigin: boot.appOrigin, documentId: controller.getState().documentId, nonce: boot.nonce, parent: window.parent },
      );
      if (message) void controller.receive(message);
    };
    window.addEventListener("message", onMessage);
    controller.announceReady();
    return () => window.removeEventListener("message", onMessage);
  }, [boot, controller]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const { action, preventDefault } = clickIntent(event.target, controller.getState().mode);
      if (preventDefault) event.preventDefault();
      const scroll = { x: window.scrollX, y: window.scrollY };
      if (action.kind === "navigate") controller.linkClicked(action.href);
      if (action.kind === "shell") {
        event.stopPropagation();
        controller.shellSelected(action.part);
        controller.annotate(SHELL_TARGET, action.part, rectOf(action.element, scroll));
      }
      if (action.kind === "component" && action.componentId) {
        controller.annotate(controller.getState().route, action.componentId, rectOf(action.element, scroll));
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const decision = shortcutFor(event);
      if (!decision) return;
      // Puck's own history and preview toggle never run: undo is the server's stack (ruling).
      event.preventDefault();
      event.stopImmediatePropagation();
      if (decision !== "swallow") controller.shortcut(decision);
    };
    const onFocusOut = () => controller.flushChange();
    document.addEventListener("click", onClick, true);
    window.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusout", onFocusOut, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusout", onFocusOut, true);
    };
  }, [controller]);

  // The shell is drawn by the page root, not by a Puck component, so its outline is ours (DR5).
  useEffect(() => {
    for (const element of document.querySelectorAll(`[${SHELL_SELECTED}]`)) element.removeAttribute(SHELL_SELECTED);
    const selection = state.selection;
    if (selection?.target === SHELL_TARGET) {
      document.querySelector(`.brand-root > ${selection.componentId}`)?.setAttribute(SHELL_SELECTED, "true");
    }
  }, [state.selection, state.mountKey]);

  const shellJson = state.site?.shell ? canonicalJson(state.site.shell) : "";
  const shell = useMemo<SiteShell | null>(() => (shellJson ? (JSON.parse(shellJson) as SiteShell) : null), [shellJson]);
  const config = useMemo(
    () => (state.brand ? buildPageConfig(state.brand, shell, state.sections) : null),
    [state.brand, shell, state.sections],
  );
  useEffect(() => {
    controller.setShellFields(state.brand ? shellFieldDescriptions(state.brand) : null);
  }, [controller, state.brand]);

  if (state.status !== "ready" || !state.site || !state.brand || !config) return null;
  const page = pageFor(state.site, state.route);
  if (!page) return null;
  const route = state.route;
  return (
    <Puck
      config={config}
      data={page as unknown as Data}
      iframe={{ enabled: false }}
      key={state.mountKey}
      onChange={(data) => controller.pageEdited(route, data as unknown as SitePage)}
      permissions={PERMISSIONS}
      ui={{
        previewMode: state.mode === "edit" ? "edit" : "interactive",
        viewports: { controlsVisible: false, current: { height: "auto", width: "100%" }, options: VIEWPORTS },
      }}
      viewports={VIEWPORTS}
    >
      <PuckBridge brand={state.brand} config={config} controller={controller} />
      <Puck.Preview />
    </Puck>
  );
}

function PuckBridge({ brand, config, controller }: { brand: BrandData; config: Config; controller: FrameController }) {
  const getPuck = useGetPuck();
  const selectedId = usePuck((store) => (store.selectedItem ? String(store.selectedItem.props.id) : null));

  useEffect(() => {
    controller.attachPuck({
      select(componentId) {
        const puck = getPuck();
        const itemSelector = componentId ? (puck.getSelectorForId(componentId) ?? null) : null;
        puck.dispatch({ type: "setUi", ui: { itemSelector } });
        if (componentId) {
          document.querySelector(`[data-puck-component="${CSS.escape(componentId)}"]`)?.scrollIntoView({ block: "nearest" });
        }
      },
      setMode(mode) {
        getPuck().dispatch({
          type: "setUi",
          ui: mode === "edit" ? { previewMode: "edit" } : { itemSelector: null, previewMode: "interactive" },
        });
      },
      showPage(page) {
        getPuck().dispatch({ data: page as unknown as Data, recordHistory: false, type: "setData" });
      },
    });
    return () => controller.attachPuck(null);
  }, [controller, getPuck]);

  useEffect(() => {
    if (!selectedId) {
      controller.componentDeselected();
      return;
    }
    const item = getPuck().getItemById(selectedId);
    if (!item) return;
    const props = item.props as Record<string, unknown>;
    controller.componentSelected(selectedId, item.type, fieldsForComponent(config, brand, item.type, props), props);
  }, [brand, config, controller, getPuck, selectedId]);

  return null;
}
```

`apps/frontend/packages/site-editor/src/client/main.tsx`:
```tsx
import "./jitless";
import { createRoot } from "react-dom/client";
import { readBootContext } from "./boot";
import { EditorApp } from "./editor-app";
import { installSectionHost } from "./host-globals";

installSectionHost();
const boot = readBootContext(
  window.location.hash,
  document.querySelector('meta[name="clue-app-origin"]')?.getAttribute("content") ?? null,
);
const container = document.getElementById("root");
// Opened directly (not framed by the app) or without a valid nonce, the editor renders nothing.
if (boot && container && window.parent !== window) {
  createRoot(container).render(<EditorApp boot={boot} />);
}
```

- [ ] **Step 6: Write the stylesheet (site-kit's Tailwind `@theme` build, Puck's CSS, two rules of ours).**

Run from the repo root:
```bash
{
  printf '%s\n' \
    '/* The site editor stylesheet: Tailwind over site-kit'"'"'s sources with the brand-token mapping the' \
    '   D2 spike proved (trials/puck-spike/app/globals.css), plus Puck'"'"'s own CSS. Agent sections bring' \
    '   their own per-module CSS (/sections/<digest>.css). */' \
    '@import "tailwindcss" source(none);' \
    '@import "@puckeditor/core/puck.css";' \
    '@source "../../../site-kit/src";' \
    ''
  sed -n '/^@theme inline {/,/^}/p' trials/puck-spike/app/globals.css
  printf '%s\n' \
    '' \
    '/* The frame fills its iframe; the page scrolls inside it. */' \
    'html, body, #root { height: 100%; margin: 0; }' \
    '#root { overflow: auto; }' \
    '' \
    '/* DESIGN REVIEW (DR5): the selected header or footer. The shell is drawn by the page root, not' \
    '   by a Puck component, so Puck draws no outline for it. */' \
    '[data-site-shell-selected] { outline: 2px solid var(--puck-color-azure-04); outline-offset: -2px; }'
} > apps/frontend/packages/site-editor/src/client/styles.css
grep -c -- '--color-surface-page: var(--brand-surface-page);' apps/frontend/packages/site-editor/src/client/styles.css
```
Expected: `1` (the `@theme inline` block was copied).

- [ ] **Step 7: Write the build and dev scripts.**

`apps/frontend/packages/site-editor/scripts/build.ts`:
```ts
// Builds the site editor into dist/: the browser bundle, its stylesheet, the import-map shims, the
// one HTML page, and the Node server bundle. React is always the production build — the editor's
// policy is the same in dev and production, and production React needs no eval.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import tailwind from "@tailwindcss/postcss";
import { build } from "esbuild";
import postcss from "postcss";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const DIST = path.join(ROOT, "dist");
const STYLES = path.join(ROOT, "src/client/styles.css");

// What a compiled agent section may import from each kept dependency (the D2 spike's list,
// trials/puck-spike/app/edit-runtime/[site]/page.tsx:20-26).
const REACT_EXPORTS = [
  "Children", "Component", "Fragment", "PureComponent", "StrictMode", "Suspense", "cloneElement",
  "createContext", "createElement", "createRef", "forwardRef", "isValidElement", "lazy", "memo",
  "startTransition", "use", "useActionState", "useCallback", "useContext", "useDebugValue",
  "useDeferredValue", "useEffect", "useId", "useImperativeHandle", "useInsertionEffect",
  "useLayoutEffect", "useMemo", "useOptimistic", "useReducer", "useRef", "useState",
  "useSyncExternalStore", "useTransition", "version",
];

export const SHIMS: Record<string, { names: readonly string[]; specifier: string }> = {
  "react-jsx-runtime.mjs": { names: ["jsx", "jsxs", "Fragment"], specifier: "react/jsx-runtime" },
  "react.mjs": { names: REACT_EXPORTS, specifier: "react" },
  "zod.mjs": { names: ["z"], specifier: "zod" },
};

export const IMPORT_MAP = JSON.stringify({
  imports: { react: "/shims/react.mjs", "react/jsx-runtime": "/shims/react-jsx-runtime.mjs", zod: "/shims/zod.mjs" },
});

export function shimSource(specifier: string, names: readonly string[]): string {
  return [
    `const m = globalThis.__clueSectionHost && globalThis.__clueSectionHost[${JSON.stringify(specifier)}];`,
    `if (!m) throw new Error(${JSON.stringify(`The site editor has not shared ${specifier} with agent sections.`)});`,
    "export default m.default ?? m;",
    `export const { ${names.join(", ")} } = m;`,
    "",
  ].join("\n");
}

export function pageHtml(scriptName: string, styleName: string): string {
  return [
    "<!doctype html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<meta name="clue-app-origin" content="%APP_ORIGIN%">',
    "<title>Site editor</title>",
    `<link rel="stylesheet" href="/assets/${styleName}">`,
    `<script type="importmap" nonce="%NONCE%">${IMPORT_MAP}</script>`,
    `<script type="module" src="/assets/${scriptName}"></script>`,
    "</head>",
    '<body><div id="root"></div></body>',
    "</html>",
    "",
  ].join("\n");
}

export async function compileStyles(): Promise<string> {
  const source = await fs.readFile(STYLES, "utf8");
  const result = await postcss([tailwind({ base: ROOT })]).process(source, { from: STYLES });
  return result.css;
}

const shortHash = (text: string) => createHash("sha256").update(text).digest("hex").slice(0, 12);

export async function buildClient(): Promise<void> {
  const result = await build({
    bundle: true,
    define: { "process.env.NODE_ENV": '"production"' },
    entryPoints: [path.join(ROOT, "src/client/main.tsx")],
    format: "esm",
    jsx: "automatic",
    logLevel: "error",
    minify: true,
    platform: "browser",
    target: "es2022",
    write: false,
  });
  const script = result.outputFiles[0].text;
  const style = await compileStyles();
  const scriptName = `editor-${shortHash(script)}.js`;
  const styleName = `editor-${shortHash(style)}.css`;
  await fs.rm(path.join(DIST, "assets"), { force: true, recursive: true });
  await fs.mkdir(path.join(DIST, "assets"), { recursive: true });
  await fs.mkdir(path.join(DIST, "shims"), { recursive: true });
  await fs.writeFile(path.join(DIST, "assets", scriptName), script);
  await fs.writeFile(path.join(DIST, "assets", styleName), style);
  for (const [file, shim] of Object.entries(SHIMS)) {
    await fs.writeFile(path.join(DIST, "shims", file), shimSource(shim.specifier, shim.names));
  }
  await fs.writeFile(path.join(DIST, "index.html"), pageHtml(scriptName, styleName));
}

export async function buildServer(): Promise<void> {
  await build({
    bundle: true,
    entryPoints: [path.join(ROOT, "src/server/main.ts")],
    format: "esm",
    logLevel: "error",
    outfile: path.join(DIST, "server.mjs"),
    platform: "node",
    target: "node22",
  });
}

export async function buildAll(): Promise<void> {
  await buildClient();
  await buildServer();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await buildAll();
  console.log(`site editor built into ${DIST}`);
}
```

`apps/frontend/packages/site-editor/scripts/dev.ts`:
```ts
// The site editor's dev loop (scripts/dev_stack.sh runs it): build everything once, serve from this
// process, and rebuild the browser bundle when the client or site-kit sources change. A change to
// the server itself needs `./scripts/dev_stack.sh restart-editor`.
import { watch } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DIST, ROOT, buildAll, buildClient } from "./build";

await buildAll();
await import(pathToFileURL(path.join(DIST, "server.mjs")).href);

let timer: ReturnType<typeof setTimeout> | null = null;
const rebuild = () => {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    buildClient()
      .then(() => console.log("site editor: client rebuilt"))
      .catch((error: unknown) => console.error("site editor: rebuild failed", error));
  }, 150);
};
for (const directory of [path.join(ROOT, "src/client"), path.join(ROOT, "../site-kit/src")]) {
  watch(directory, { recursive: true }, rebuild);
}
```

In `apps/frontend/packages/site-editor/package.json`, replace `"scripts"` with:
```json
  "scripts": {
    "build": "tsx scripts/build.ts",
    "dev": "tsx scripts/dev.ts",
    "start": "node dist/server.mjs",
    "test": "tsx --test test/*.test.ts",
    "typecheck": "tsc --noEmit"
  },
```
In `apps/frontend/packages/site-editor/tsconfig.json`, set `"include": ["src", "test", "scripts"]`.

- [ ] **Step 8: Run the unit tests, the type-check and the build.**

Run: `cd apps/frontend && npm test -w @clue/site-editor 2>&1 | tail -5 && npm run typecheck -w @clue/site-editor && npm run build -w @clue/site-editor`
Expected: 8 + 1 + 2 + 6 + 3 + 10 + 3 = 33 passing, 0 failing; no type errors; the build prints `site editor built into …/apps/frontend/packages/site-editor/dist`, and `ls apps/frontend/packages/site-editor/dist` lists `assets  index.html  server.mjs  shims`.

- [ ] **Step 9: Smoke the built server by hand.**

Run (two shells, from `apps/frontend`):
```bash
PORT=3199 HOST=127.0.0.1 CLUE_APP_ORIGIN=http://localhost:3029 LUMEN_API_BASE_URL=http://127.0.0.1:8019 CLUE_SITE_EDITOR_SUFFIX=editor.localhost:3199 node packages/site-editor/dist/server.mjs
curl -s -D - -o /dev/null -H 'Host: aac8c47153e8e006ea26797aa03615b6.editor.localhost:3199' http://127.0.0.1:3199/ | grep -i -E '^(HTTP|content-security-policy)'
```
Expected: `HTTP/1.1 200 OK` and a `content-security-policy:` line containing `script-src 'self' 'nonce-` and `frame-ancestors http://localhost:3029`. Stop the server (Ctrl-C).

- [ ] **Step 10: Write the browser harness and the renders test.**

`apps/frontend/packages/site-editor/test/browser/fixture-init.ts`:
```ts
// Prints {site, brand} for the browser harness: the Garner × Syracuse site and brand from
// site-kit's test fixtures, as a Contract 1 site document.
import { garner, site } from "../../../site-kit/test/fixtures/garner";

const stored = site("garner-syracuse");
const document = {
  agent_sections: {},
  id: "doc_probe",
  pages: stored.pages,
  shell: stored.shell,
  theme: {},
  title: "Garner × Syracuse",
};
process.stdout.write(JSON.stringify({ brand: garner(), site: document }));
```

`tests/site_editor/__init__.py`: an empty file.

`tests/site_editor/conftest.py`:
```python
"""Browser harness for the site editor (Lane C). Every test here is opt-in.

It starts, on free ports: a stub design API (the token-checked section route, plan K1, and nothing
else), a stub app page that embeds the editor exactly as the app does (sandboxed iframe, nonce in
the URL fragment, the Contract 6 envelope, exact target origins), and the BUILT editor server at
http://<label>.editor.localhost:<port>. Build first:
    cd apps/frontend && npm run build -w @clue/site-editor
Playwright's Chromium must be installed in the repo venv (DEV_STACK.md prerequisites).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "apps/frontend"
EDITOR = FRONTEND / "packages/site-editor"
WORKSPACE_ID = "ws_containment_probe"
LABEL = hashlib.sha256(f"clue-site-editor-label:v1:{WORKSPACE_ID}".encode()).hexdigest()[:32]
TOKEN = "probe-token-0123456789abcdef"
NONCE = "harness-nonce-0123456789"
COOKIE_SECRET = "clue-session-secret-value"

BROWSER_OPT_IN = pytest.mark.skipif(
    os.environ.get("CLUE_SITE_EDITOR_BROWSER") != "1",
    reason="browser test: set CLUE_SITE_EDITOR_BROWSER=1 after `npm run build -w @clue/site-editor`",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler's name
        return


def _serve(handler: type[http.server.BaseHTTPRequestHandler], port: int) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@dataclass
class DesignApiStub:
    port: int
    modules: dict[str, bytes] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)


@dataclass
class AppStub:
    port: int
    init_payload: dict[str, Any] = field(default_factory=dict)
    secret_hits: list[str] = field(default_factory=list)

    @property
    def origin(self) -> str:
        return f"http://localhost:{self.port}"


HOST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>app stub</title></head><body>
<script>
const EDITOR = __EDITOR__;
const NONCE = __NONCE__;
const INIT = __INIT__;
window.__received = [];
const frame = document.createElement("iframe");
frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
frame.setAttribute("referrerpolicy", "no-referrer");
frame.style.width = "1280px"; frame.style.height = "2400px"; frame.style.border = "0";
frame.src = EDITOR + "/#n=" + NONCE;
document.body.appendChild(frame);
window.__send = (type, payload) => frame.contentWindow.postMessage(
  { channel: "clue-site-editor", v: 1, documentId: "doc_probe", nonce: NONCE, type, payload }, EDITOR);
window.addEventListener("message", (event) => {
  if (event.origin !== EDITOR || event.source !== frame.contentWindow) return;
  const message = event.data;
  if (!message || message.channel !== "clue-site-editor" || message.v !== 1 || message.nonce !== NONCE) return;
  window.__received.push(message);
  if (message.type === "ready") window.__send("init", INIT);
});
</script></body></html>"""

CSP_RECORDER = """
window.__csp = [];
document.addEventListener("securitypolicyviolation", (event) => {
  window.__csp.push({ directive: event.effectiveDirective, blocked: event.blockedURI });
});
"""


@pytest.fixture(scope="session")
def design_api() -> Iterator[DesignApiStub]:
    stub = DesignApiStub(port=free_port())

    class Handler(_Quiet):
        def do_GET(self) -> None:  # noqa: N802 - http.server's method name
            stub.requests.append(self.path)
            path, _, query = self.path.partition("?")
            match = re.fullmatch(r"/site-sections/([0-9a-f]{64})\.(mjs|css)", path)
            if match and query == f"t={TOKEN}":
                digest, extension = match.groups()
                body = stub.modules.get(digest) if extension == "mjs" else b""
                if body is not None:
                    self.send_response(200)
                    self.send_header("content-type", "text/javascript" if extension == "mjs" else "text/css")
                    self.send_header("x-clue-workspace-id", WORKSPACE_ID)
                    self.end_headers()
                    self.wfile.write(body)
                    return
            self.send_response(404)
            self.end_headers()

    server = _serve(Handler, stub.port)
    yield stub
    server.shutdown()


@pytest.fixture(scope="session")
def editor_port() -> int:
    return free_port()


@pytest.fixture(scope="session")
def editor_origin(editor_port: int) -> str:
    return f"http://{LABEL}.editor.localhost:{editor_port}"


@pytest.fixture(scope="session")
def app(editor_origin: str) -> Iterator[AppStub]:
    stub = AppStub(port=free_port())

    class Handler(_Quiet):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/secret"):
                stub.secret_hits.append(self.headers.get("cookie") or "")
                self.send_response(200)
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()
                self.wfile.write(b"secret")
                return
            page = (
                HOST_PAGE.replace("__EDITOR__", json.dumps(editor_origin))
                .replace("__NONCE__", json.dumps(NONCE))
                .replace("__INIT__", json.dumps(stub.init_payload))
            )
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("set-cookie", f"clue_session={COOKIE_SECRET}; Path=/; SameSite=Lax")
            self.end_headers()
            self.wfile.write(page.encode())

    server = _serve(Handler, stub.port)
    yield stub
    server.shutdown()


@pytest.fixture(scope="session")
def editor_server(design_api: DesignApiStub, app: AppStub, editor_port: int) -> Iterator[None]:
    server_bundle = EDITOR / "dist" / "server.mjs"
    if not server_bundle.exists():
        pytest.fail("Build the editor first: cd apps/frontend && npm run build -w @clue/site-editor")
    env = {
        **os.environ,
        "CLUE_APP_ORIGIN": app.origin,
        "CLUE_SITE_EDITOR_SUFFIX": f"editor.localhost:{editor_port}",
        "HOST": "127.0.0.1",
        "LUMEN_API_BASE_URL": f"http://127.0.0.1:{design_api.port}",
        "PORT": str(editor_port),
    }
    process = subprocess.Popen(
        ["node", str(server_bundle)], cwd=EDITOR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    deadline = time.time() + 15
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{editor_port}/healthz", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            if time.time() > deadline:
                process.kill()
                pytest.fail("the editor server did not start")
            time.sleep(0.2)
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture()
def browser_page(editor_server: None) -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        context.add_init_script(script=CSP_RECORDER)
        page = context.new_page()
        yield page, context
        context.close()
        browser.close()


def editor_frame(page: Any, editor_origin: str) -> Any:
    deadline = time.time() + 20
    while time.time() < deadline:
        for frame in page.frames:
            if frame.url.startswith(editor_origin):
                return frame
        page.wait_for_timeout(100)
    raise AssertionError("the editor frame never loaded")


def received(page: Any) -> list[dict[str, Any]]:
    return page.evaluate("window.__received")


def garner_init(mode: str = "edit") -> dict[str, Any]:
    output = subprocess.run(
        ["npx", "tsx", "packages/site-editor/test/browser/fixture-init.ts"],
        capture_output=True,
        check=True,
        cwd=FRONTEND,
        text=True,
    ).stdout
    fixture = json.loads(output)
    return {"brand": fixture["brand"], "device": "Desktop", "mode": mode, "route": "/", "sections": [], "site": fixture["site"]}
```

`tests/site_editor/test_editor_renders.py`:
```python
"""Lane C task C3: the built editor renders a site under its own policy and speaks Contract 6."""

from __future__ import annotations

from typing import Any

from .conftest import BROWSER_OPT_IN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN
PROOF = "7.4% lower medical spend in year one. No plan changes."


def test_the_editor_renders_a_site_and_reports_selections(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, _ = browser_page
    app.init_payload = garner_init()
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    assert [message["type"] for message in received(page)][:2] == ["ready", "navigated"]

    page.wait_for_timeout(1500)  # longer than the 600 ms change debounce
    assert "changed" not in [message["type"] for message in received(page)], "opening a site must not save it"
    own_code = [v for v in frame.evaluate("window.__csp") if v["directive"].startswith(("script-src", "style-src", "frame-src", "connect-src"))]
    assert own_code == [], f"the editor's own code must run under its policy: {own_code}"

    frame.get_by_text(PROOF).first.click()
    page.wait_for_function("window.__received.some((m) => m.type === 'selected')")
    selected = next(message for message in received(page) if message["type"] == "selected")
    assert selected["payload"]["componentId"] == "proof"
    assert selected["payload"]["componentType"] == "StatsBand"
    assert any(f["name"] == "heading" and f["kind"] == "text" for f in selected["payload"]["fields"])
    assert any(m["type"] == "annotate" and m["payload"]["componentId"] == "proof" for m in received(page))

    frame.locator(".brand-root > header").click()
    page.wait_for_function("window.__received.some((m) => m.type === 'selected' && m.payload.route === 'shell')")
    shell = [m for m in received(page) if m["type"] == "selected" and m["payload"]["route"] == "shell"][-1]
    assert shell["payload"]["componentId"] == "header"
    assert frame.locator(".brand-root > header[data-site-shell-selected]").count() == 1


def test_the_app_navigates_the_frame_and_the_frame_never_navigates_the_app(app: Any, browser_page: Any, editor_origin: str) -> None:
    page, _ = browser_page
    app.init_payload = garner_init(mode="preview")
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)
    frame.get_by_text(PROOF).first.wait_for(timeout=20000)
    page.evaluate("window.__send('navigate', { route: '/analysis' })")
    page.wait_for_function("window.__received.some((m) => m.type === 'navigated' && m.payload.route === '/analysis')")
    frame.get_by_text("Request SCSD's free analysis").first.wait_for(timeout=10000)
    assert page.url == app.origin + "/"
```

- [ ] **Step 11: Run the browser test.**

Run: `cd apps/frontend && npm run build -w @clue/site-editor && cd ../.. && CLUE_SITE_EDITOR_BROWSER=1 .venv/bin/python -m pytest tests/site_editor/test_editor_renders.py -q`
Expected: `2 passed`. Without `CLUE_SITE_EDITOR_BROWSER=1` the same command reports `2 skipped` (so `make check` never needs a browser).

If the first test fails on the CSP assertion with a `frame-src` violation, Puck is still creating its canvas iframe: confirm `iframe={{ enabled: false }}` reached `<Puck>` — do not relax `frame-src`.

- [ ] **Step 12: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 13: Commit.**
```bash
git add apps/frontend/packages/site-editor tests/site_editor
git commit -m "site editor: the canvas-only Puck client (Contract 6, runtime sections behind the CSP, shell selection), its build, and the browser harness"
```

---

### Task 7: C4a — the workspace's editor origin, served to the browser (Contract 9)

The browser never sees the workspace id, so it cannot derive its own label. A small authenticated route computes `https://<label>.<CLUE_SITE_EDITOR_SUFFIX>` server-side from the re-authorized workspace (the same `authenticatedBackendContext()` the design BFF uses) and returns it. Env is read in exactly one place (`src/auth/config.ts`).

**Files:**
- Modify: `apps/frontend/src/auth/config.ts` (add `siteEditorSuffix()`)
- Create: `apps/frontend/src/features/site-editor/server/site-editor-session-handler.ts`
- Create: `apps/frontend/src/features/site-editor/server/site-editor-session-handler.test.ts`
- Create: `apps/frontend/src/app/api/clue/site-editor/session/route.ts`
- Create: `apps/frontend/src/features/site-editor/data/site-editor-session.ts`
- Create: `apps/frontend/src/features/site-editor/data/site-editor-session.test.ts`

**Interfaces:**
- Consumes: `@clue/site-kit/editor-origin` (`editorLabelFor`, `editorOriginFor`) from Task 4; `ClueAuthenticationError` (`src/auth/errors.ts`); `authenticatedBackendContext` (`src/auth/authenticated-backend.ts`).
- Produces:
  - `siteEditorSuffix(): string` (empty when unset).
  - `handleSiteEditorSession(deps: { authenticationEnabled: boolean; editorSuffix: string; workspaceId: () => Promise<string> }): Promise<Response>` → `200 { data: { editorOrigin: string | null } }` with `cache-control: no-store`; the auth error's own status for an unauthenticated request; `500 { error: { code: "SITE_EDITOR_MISCONFIGURED" } }` for a malformed suffix.
  - `GET /api/clue/site-editor/session`.
  - `fetchSiteEditorSession(fetchImpl?: typeof fetch): Promise<{ editorOrigin: string | null }>`.

- [ ] **Step 1: Write the failing tests.**

`apps/frontend/src/features/site-editor/server/site-editor-session-handler.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { ClueAuthenticationError } from "@/auth/errors";
import { handleSiteEditorSession } from "./site-editor-session-handler";

test("an authenticated workspace gets its own editor origin, never cached", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "editor.localhost:3129",
    workspaceId: async () => "ws_123",
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), {
    data: { editorOrigin: "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129" },
  });
});

test("no editor domain configured, or authentication off, means no origin", async () => {
  for (const deps of [
    { authenticationEnabled: true, editorSuffix: "" },
    { authenticationEnabled: false, editorSuffix: "edit.example.com" },
  ]) {
    const response = await handleSiteEditorSession({ ...deps, workspaceId: async () => "ws_123" });
    assert.deepEqual(await response.json(), { data: { editorOrigin: null } });
  }
});

test("an unauthenticated request is refused with the authentication error's own status", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "edit.example.com",
    workspaceId: async () => {
      throw new ClueAuthenticationError("Sign in to continue", { code: "AUTHENTICATION_REQUIRED", status: 401 });
    },
  });
  assert.equal(response.status, 401);
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, "AUTHENTICATION_REQUIRED");
});

test("a malformed suffix fails loudly instead of producing a wrong origin", async () => {
  const response = await handleSiteEditorSession({
    authenticationEnabled: true,
    editorSuffix: "https://edit.example.com",
    workspaceId: async () => "ws_123",
  });
  assert.equal(response.status, 500);
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, "SITE_EDITOR_MISCONFIGURED");
});
```

`apps/frontend/src/features/site-editor/data/site-editor-session.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchSiteEditorSession } from "./site-editor-session";

test("the session read returns the editor origin, or null when none is configured", async () => {
  const calls: string[] = [];
  const answer = (editorOrigin: string | null) =>
    (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify({ data: { editorOrigin } }), { status: 200 });
    }) as typeof fetch;
  assert.deepEqual(await fetchSiteEditorSession(answer("https://aac8c47153e8e006ea26797aa03615b6.edit.example.com")), {
    editorOrigin: "https://aac8c47153e8e006ea26797aa03615b6.edit.example.com",
  });
  assert.deepEqual(await fetchSiteEditorSession(answer(null)), { editorOrigin: null });
  assert.equal(calls[0], "/api/clue/site-editor/session");
});

test("a refused session read throws with its status", async () => {
  const refused = (async () => new Response("{}", { status: 401 })) as typeof fetch;
  await assert.rejects(fetchSiteEditorSession(refused), /HTTP 401/);
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/server/site-editor-session-handler.test.ts src/features/site-editor/data/site-editor-session.test.ts`
Expected: FAIL — `Cannot find module './site-editor-session-handler'`.

- [ ] **Step 3: Read the setting in the one env module.**

In `apps/frontend/src/auth/config.ts`, add after `clueAppOrigin()`:
```ts
/** Wave 2 Contract 9: the site editor's domain suffix (`<label>.<suffix>`). Empty = no editor
 * domain is configured; a site then shows the canvas error state. */
export function siteEditorSuffix(): string {
  return process.env.CLUE_SITE_EDITOR_SUFFIX?.trim().toLowerCase() ?? "";
}
```

- [ ] **Step 4: Write the handler, the route and the client read.**

`apps/frontend/src/features/site-editor/server/site-editor-session-handler.ts`:
```ts
import { editorLabelFor, editorOriginFor } from "@clue/site-kit/editor-origin";
import { ClueAuthenticationError } from "@/auth/errors";

export interface SiteEditorSessionDeps {
  authenticationEnabled: boolean;
  editorSuffix: string;
  /** The re-authorized workspace id (server-side only; it never reaches the browser). */
  workspaceId: () => Promise<string>;
}

const NO_STORE = { "cache-control": "no-store" };

function refusal(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, requestId: null } }, { headers: NO_STORE, status });
}

/** Contract 9: the editor origin for THIS workspace — `https://<label>.<suffix>`, the label an
 * opaque token derived from the workspace id. Testable without Next (the route only composes it). */
export async function handleSiteEditorSession(deps: SiteEditorSessionDeps): Promise<Response> {
  if (!deps.authenticationEnabled || !deps.editorSuffix) {
    return Response.json({ data: { editorOrigin: null } }, { headers: NO_STORE });
  }
  let workspaceId: string;
  try {
    workspaceId = await deps.workspaceId();
  } catch (error) {
    if (error instanceof ClueAuthenticationError) return refusal(error.status, error.code, error.message);
    throw error;
  }
  let editorOrigin: string;
  try {
    editorOrigin = editorOriginFor(await editorLabelFor(workspaceId), deps.editorSuffix);
  } catch {
    return refusal(500, "SITE_EDITOR_MISCONFIGURED", "CLUE_SITE_EDITOR_SUFFIX is not a domain suffix");
  }
  return Response.json({ data: { editorOrigin } }, { headers: NO_STORE });
}
```

`apps/frontend/src/app/api/clue/site-editor/session/route.ts`:
```ts
import { authenticatedBackendContext } from "@/auth/authenticated-backend";
import { isAuthenticationEnabled, siteEditorSuffix } from "@/auth/config";
import { handleSiteEditorSession } from "@/features/site-editor/server/site-editor-session-handler";

/**
 * Lane C / Contract 9: the browser's read of its workspace's site-editor origin. The label is
 * derived here from the re-authorized workspace id, which never reaches the browser. GET handlers
 * are dynamic by default in this Next version (route.md, v15 change), and this one reads cookies.
 */
export async function GET() {
  return handleSiteEditorSession({
    authenticationEnabled: isAuthenticationEnabled(),
    editorSuffix: siteEditorSuffix(),
    workspaceId: async () => (await authenticatedBackendContext()).workspaceId,
  });
}
```

`apps/frontend/src/features/site-editor/data/site-editor-session.ts`:
```ts
import { z } from "zod";

const SiteEditorSessionWireSchema = z.object({ data: z.object({ editorOrigin: z.url().nullable() }) });

/** The workspace's site-editor origin, or null when no editor domain is configured. */
export async function fetchSiteEditorSession(
  fetchImpl: typeof fetch = (input, init) => fetch(input, init),
): Promise<{ editorOrigin: string | null }> {
  const response = await fetchImpl("/api/clue/site-editor/session", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`The website editor session could not be read (HTTP ${response.status}).`);
  }
  return SiteEditorSessionWireSchema.parse(await response.json()).data;
}
```

- [ ] **Step 5: Run the tests.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/server/site-editor-session-handler.test.ts src/features/site-editor/data/site-editor-session.test.ts`
Expected: 6 passing, 0 failing.

- [ ] **Step 6: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0; the route table lists `ƒ /api/clue/site-editor/session`.

- [ ] **Step 7: Commit.**
```bash
git add apps/frontend/src/auth/config.ts apps/frontend/src/features/site-editor apps/frontend/src/app/api/clue/site-editor
git commit -m "site editor: the workspace's editor origin (Contract 9) computed server-side and read by the browser"
```

---

### Task 8: C4b — the app's frame host: the persistent site stage, the protocol host and the editing session

This task makes a site open in the stage. The app mounts **one** iframe onto the workspace's editor origin (`sandbox="allow-scripts allow-same-origin"`, `referrerPolicy="no-referrer"`, nonce in the URL fragment), keeps it mounted while hidden — warm from the moment the project has a site or an open design leg — and drives it with Contract 6: `init` for a new document, a new set of agent sections or a rebooted frame; `replace_site` for a new version of the same document; `set_mode` for edit/preview. Every inbound message passes `acceptFrameMessage` (exact editor origin, the iframe's window, the frame's nonce, the initialised document). The stage shows the web canvas's three states — "Loading preview…", "Preview failed", "Your website will render here" — extracted into a shared component so both canvases render the same markup.

The app holds the site JSON: a `changed` from the frame is adopted and saved through Task 3's policy, but only while editing and not locked (Review focus 5).

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-stage.ts` (binding types + `siteStageMounted`)
- Create: `apps/frontend/src/features/site-editor/model/site-canvas-state.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/site-editor/model/site-frame-sync.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-editor-origin.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-document.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-frame-host.ts`
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`
- Create: `apps/frontend/src/features/design-editor/components/canvas-states.tsx`
- Create: `apps/frontend/src/features/design-editor/components/site-artifact-canvas.tsx`
- Modify: `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx:513-540` (use the shared states)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (the persistent site stage)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (`.siteStage[hidden]`)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (session, lock, reloads, stage props)
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` (same, with the document-scoped lock)

**Interfaces:**
- Consumes: Task 3 (`SiteRepository`, `httpSiteRepository`, `LoadedSite`, `useSiteSaves`, `SiteSaves`), Task 4 (`acceptFrameMessage`, `appToFrame`, types, `canonicalJson`, `sectionDigests`), Task 7 (`fetchSiteEditorSession`), `AGENT_RUN_LOCK_NOTE` (`chat-shell/model/agent-run-lock.ts`), `VeilRenderKind` (`design-editor/adapter/generating-veil.ts`).
- Produces:
  - `model/site-stage.ts`: `interface SiteCanvasBinding { errorMessage: string | null; iframeRef: RefObject<HTMLIFrameElement | null>; renderKind: VeilRenderKind; src: string | null }`, `interface SiteStageBinding { mounted: boolean; canvas: SiteCanvasBinding }`, `siteStageMounted(input: { enabled: boolean; warm: boolean; editorOrigin: string | null }): boolean`.
  - `model/site-canvas-state.ts`: `EDITOR_NOT_CONFIGURED`, `SITE_LOAD_FAILED`, `siteIsEmpty(site): boolean`, `siteCanvasState(input): { kind: VeilRenderKind; message: string | null }`.
  - `model/site-frame-sync.ts`: `SECTION_LINK_REFRESH_MS`, `siteInitKey(documentId, site, frameBoot): string`, `frameSyncFor(input): { kind: "init" } | { kind: "replace"; version: number } | { kind: "none" }`, `linksFresh(loadedAt, now, linkCount): boolean`, `siteFrameMode({ editing, locked }): EditorMode`, `acceptsFrameEdits({ editing, locked }): boolean`, `initialRoute(site, wanted): string`.
  - `hooks/use-site-frame-host.ts`: `useSiteFrameHost({ editorOrigin, onMessage }): { iframeRef; src: string | null; boot: number; post<T>(type, payload, documentId): void }`.
  - `hooks/use-site-editing-session.ts`: `useSiteEditingSession(options: { activeArtifactId: string | null; documentIds: Record<string, string> | undefined; editing: boolean; enabled: boolean; locked: boolean; warm: boolean; repository?: SiteRepository }): SiteEditingSession` with `SiteEditingSession = { activeDocumentId: string | null; reload(): void; reloadNonce: number; route: string; saves: SiteSaves; site: SiteDocument | null; setSite(site: SiteDocument): void; version: number | null; stage: SiteStageBinding; post: SiteFrameHost["post"] }`. Tasks 9–14 extend this session in place: each adds its own cases to `handleFrameMessage`'s switch and its own members to the returned object.
  - `ArtifactStage` prop `site?: SiteStageBinding | null`.
  - `design-editor/components/canvas-states.tsx`: `CanvasLoadingState()`, `CanvasErrorState({ message })`, `CanvasEmptyState()`.

- [ ] **Step 1: Write the failing model tests.**

`apps/frontend/src/features/site-editor/model/site-frame-sync.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import {
  SECTION_LINK_REFRESH_MS,
  acceptsFrameEdits,
  frameSyncFor,
  initialRoute,
  linksFresh,
  siteFrameMode,
  siteInitKey,
} from "./site-frame-sync";

const site = (sections: Record<string, string> = {}) =>
  SiteDocumentSchema.parse({
    id: "doc-a",
    title: "A",
    theme: {},
    pages: { "/": { root: { props: {} }, content: [] }, "/analysis": { root: { props: {} }, content: [] } },
    shell: null,
    agent_sections: sections,
  });

test("a booted frame gets an init first, then replace_site for each new version", () => {
  const key = siteInitKey("doc-a", site(), 1);
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: null, sentVersion: null, version: 3 }), { kind: "init" });
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: key, sentVersion: 3, version: 3 }), { kind: "none" });
  assert.deepEqual(frameSyncFor({ frameReady: true, initKey: key, sentInitKey: key, sentVersion: 3, version: 4 }), {
    kind: "replace",
    version: 4,
  });
  assert.deepEqual(frameSyncFor({ frameReady: false, initKey: key, sentInitKey: null, sentVersion: null, version: 3 }), { kind: "none" });
});

test("Review focus 2: another document, new agent sections or a rebooted frame each need a fresh init", () => {
  const base = siteInitKey("doc-a", site(), 1);
  assert.notEqual(siteInitKey("doc-b", site(), 1), base, "switching documents re-initialises");
  assert.notEqual(siteInitKey("doc-a", site({ AnalysisSteps: "a".repeat(64) }), 1), base, "a new agent section re-initialises");
  assert.notEqual(siteInitKey("doc-a", site(), 2), base, "a frame that booted again re-initialises");
  assert.equal(siteInitKey("doc-a", site(), 1), base);
});

test("Review focus 4: section links older than eight minutes are refetched before an init", () => {
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS - 1, 2), true);
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS, 2), false);
  assert.equal(linksFresh(0, SECTION_LINK_REFRESH_MS * 10, 0), true, "a site with no agent sections has nothing to refresh");
});

test("Review focus 5: the frame edits, and the app accepts edits, only while editing and unlocked", () => {
  assert.equal(siteFrameMode({ editing: true, locked: false }), "edit");
  assert.equal(siteFrameMode({ editing: true, locked: true }), "preview");
  assert.equal(siteFrameMode({ editing: false, locked: false }), "preview");
  assert.equal(acceptsFrameEdits({ editing: true, locked: false }), true);
  assert.equal(acceptsFrameEdits({ editing: true, locked: true }), false);
  assert.equal(acceptsFrameEdits({ editing: false, locked: false }), false);
});

test("an init opens the page the user was on when the site still has it, else home", () => {
  assert.equal(initialRoute(site(), "/analysis"), "/analysis");
  assert.equal(initialRoute(site(), "/gone"), "/");
  assert.equal(initialRoute(site(), null), "/");
});
```

`apps/frontend/src/features/site-editor/model/site-canvas-state.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { EDITOR_NOT_CONFIGURED, siteCanvasState, type SiteCanvasInputs } from "./site-canvas-state";
import { siteStageMounted } from "./site-stage";

const filled = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta" } }] } },
  shell: null,
  agent_sections: {},
});
const empty = { ...filled, pages: { "/": { root: { props: {} }, content: [] } } };
const READY: SiteCanvasInputs = {
  documentId: "doc-a",
  editorOrigin: "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129",
  editorOriginError: null,
  editorOriginLoaded: true,
  frameError: null,
  frameReady: true,
  loadError: null,
  loadStatus: "ready",
  shownDocumentId: "doc-a",
  site: filled,
};

test("the canvas is ready only when the frame shows THIS document", () => {
  assert.deepEqual(siteCanvasState(READY), { kind: "ready", message: null });
  assert.equal(siteCanvasState({ ...READY, shownDocumentId: "doc-b" }).kind, "loading");
  assert.equal(siteCanvasState({ ...READY, frameReady: false }).kind, "loading");
  assert.equal(siteCanvasState({ ...READY, loadStatus: "loading" }).kind, "loading");
});

test("no document is the empty state; a site with no sections yet is the empty state too", () => {
  assert.equal(siteCanvasState({ ...READY, documentId: null }).kind, "empty");
  assert.equal(siteCanvasState({ ...READY, frameReady: false, site: empty }).kind, "empty");
});

test("an unconfigured editor domain, a failed load or a frame error is the error state with its words", () => {
  assert.deepEqual(siteCanvasState({ ...READY, editorOrigin: null }), { kind: "error", message: EDITOR_NOT_CONFIGURED });
  assert.deepEqual(siteCanvasState({ ...READY, editorOrigin: null, editorOriginError: "HTTP 401" }), { kind: "error", message: "HTTP 401" });
  assert.deepEqual(siteCanvasState({ ...READY, loadError: "No such website.", loadStatus: "error" }), {
    kind: "error",
    message: "No such website.",
  });
  assert.deepEqual(siteCanvasState({ ...READY, frameError: "The section AnalysisSteps could not be loaded" }), {
    kind: "error",
    message: "The section AnalysisSteps could not be loaded",
  });
});

test("the frame is mounted for an open site, and kept warm only once an editor origin exists", () => {
  assert.equal(siteStageMounted({ editorOrigin: null, enabled: true, warm: false }), true, "an open site shows its states even unconfigured");
  assert.equal(siteStageMounted({ editorOrigin: null, enabled: false, warm: true }), false);
  assert.equal(siteStageMounted({ editorOrigin: "http://x.editor.localhost:3129", enabled: false, warm: true }), true);
  assert.equal(siteStageMounted({ editorOrigin: "http://x.editor.localhost:3129", enabled: false, warm: false }), false);
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-frame-sync.test.ts src/features/site-editor/model/site-canvas-state.test.ts`
Expected: FAIL — `Cannot find module './site-frame-sync'`.

- [ ] **Step 3: Write the three models.**

`apps/frontend/src/features/site-editor/model/site-stage.ts`:
```ts
import type { RefObject } from "react";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";

/** What the stage needs to draw the site canvas. */
export interface SiteCanvasBinding {
  errorMessage: string | null;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  renderKind: VeilRenderKind;
  src: string | null;
}

/** The persistent site stage: mounted while a site is open, or warm (the project has a site or an
 * open design leg) once the workspace has an editor origin. Later tasks add pages and the URL bar. */
export interface SiteStageBinding {
  canvas: SiteCanvasBinding;
  mounted: boolean;
}

export function siteStageMounted(input: { editorOrigin: string | null; enabled: boolean; warm: boolean }): boolean {
  return input.enabled || (input.warm && input.editorOrigin !== null);
}
```

`apps/frontend/src/features/site-editor/model/site-canvas-state.ts`:
```ts
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { VeilRenderKind } from "@/features/design-editor/adapter/generating-veil";

export const EDITOR_NOT_CONFIGURED = "The website editor is not configured for this environment.";
export const SITE_LOAD_FAILED = "The website could not be loaded.";

export interface SiteCanvasInputs {
  documentId: string | null;
  editorOrigin: string | null;
  editorOriginError: string | null;
  editorOriginLoaded: boolean;
  frameError: string | null;
  frameReady: boolean;
  loadError: string | null;
  loadStatus: "idle" | "loading" | "ready" | "error";
  shownDocumentId: string | null;
  site: SiteDocument | null;
}

export function siteIsEmpty(site: SiteDocument): boolean {
  return Object.values(site.pages).every((page) => page.content.length === 0);
}

/** Which of the web canvas's three states (or the frame itself) the site canvas shows. */
export function siteCanvasState(input: SiteCanvasInputs): { kind: VeilRenderKind; message: string | null } {
  if (!input.documentId) return { kind: "empty", message: null };
  if (input.editorOriginLoaded && !input.editorOrigin) {
    return { kind: "error", message: input.editorOriginError ?? EDITOR_NOT_CONFIGURED };
  }
  if (input.loadStatus === "error") return { kind: "error", message: input.loadError ?? SITE_LOAD_FAILED };
  if (input.frameError) return { kind: "error", message: input.frameError };
  if (input.site && input.loadStatus === "ready" && siteIsEmpty(input.site)) return { kind: "empty", message: null };
  if (!input.editorOrigin || input.loadStatus !== "ready" || !input.frameReady || input.shownDocumentId !== input.documentId) {
    return { kind: "loading", message: null };
  }
  return { kind: "ready", message: null };
}
```

`apps/frontend/src/features/site-editor/model/site-frame-sync.ts`:
```ts
import type { EditorMode } from "@clue/site-kit/editor-protocol";
import { pageFor, sectionDigests } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

/** Contract 4: a section link lives ten minutes; anything older than eight is refetched first. */
export const SECTION_LINK_REFRESH_MS = 8 * 60_000;

/** What an init depends on: the frame's boot, the document and its agent sections. */
export function siteInitKey(documentId: string, site: SiteDocument, frameBoot: number): string {
  return `${frameBoot}|${documentId}|${sectionDigests(site).join(",")}`;
}

export type FrameSync = { kind: "init" } | { kind: "replace"; version: number } | { kind: "none" };

export function frameSyncFor(input: {
  frameReady: boolean;
  initKey: string;
  sentInitKey: string | null;
  sentVersion: number | null;
  version: number;
}): FrameSync {
  if (!input.frameReady) return { kind: "none" };
  if (input.initKey !== input.sentInitKey) return { kind: "init" };
  if (input.version !== input.sentVersion) return { kind: "replace", version: input.version };
  return { kind: "none" };
}

export function linksFresh(loadedAt: number, now: number, linkCount: number): boolean {
  return linkCount === 0 || now - loadedAt < SECTION_LINK_REFRESH_MS;
}

/** Ruling: the agent-run lock applies to sites — while it holds, the canvas is a preview. */
export function siteFrameMode({ editing, locked }: { editing: boolean; locked: boolean }): EditorMode {
  return editing && !locked ? "edit" : "preview";
}

/** The app is the only side that saves, and it saves frame edits only in edit mode, unlocked. */
export function acceptsFrameEdits({ editing, locked }: { editing: boolean; locked: boolean }): boolean {
  return editing && !locked;
}

export function initialRoute(site: SiteDocument, wanted: string | null): string {
  return wanted && pageFor(site, wanted) ? wanted : "/";
}
```

- [ ] **Step 4: Run the model tests.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-frame-sync.test.ts src/features/site-editor/model/site-canvas-state.test.ts`
Expected: 9 passing, 0 failing.

- [ ] **Step 5: Write the three small hooks.**

`apps/frontend/src/features/site-editor/hooks/use-site-editor-origin.ts`:
```ts
"use client";

import { useEffect, useState } from "react";
import { fetchSiteEditorSession } from "../data/site-editor-session";

export interface SiteEditorOrigin {
  error: string | null;
  loaded: boolean;
  origin: string | null;
}

// One read per page: every mount shares it; a failed read is retried by the next mount.
let shared: Promise<string | null> | null = null;
function loadOrigin(): Promise<string | null> {
  shared ??= fetchSiteEditorSession()
    .then((session) => session.editorOrigin)
    .catch((error: unknown) => {
      shared = null;
      throw error;
    });
  return shared;
}

export function useSiteEditorOrigin(enabled: boolean): SiteEditorOrigin {
  const [state, setState] = useState<SiteEditorOrigin>({ error: null, loaded: false, origin: null });
  useEffect(() => {
    if (!enabled || state.loaded) return;
    let live = true;
    loadOrigin()
      .then((origin) => {
        if (live) setState({ error: null, loaded: true, origin });
      })
      .catch((error: unknown) => {
        if (live) setState({ error: error instanceof Error ? error.message : String(error), loaded: true, origin: null });
      });
    return () => {
      live = false;
    };
  }, [enabled, state.loaded]);
  return state;
}
```

`apps/frontend/src/features/site-editor/hooks/use-site-document.ts`:
```ts
"use client";

import { useEffect, useRef, useState } from "react";
import type { BrandData } from "@clue/site-kit";
import type { SectionLink } from "@clue/site-kit/site-document";
import type { SiteRepository } from "../data/site.repository";
import type { LoadedSite } from "../model/site-wire";

export interface SiteDocumentLoad {
  brand: BrandData | null;
  error: string | null;
  links: SectionLink[];
  loaded: LoadedSite | null;
  loadedAt: number;
  status: "idle" | "loading" | "ready" | "error";
}

const IDLE: SiteDocumentLoad = { brand: null, error: null, links: [], loaded: null, loadedAt: 0, status: "idle" };
const LOADING: SiteDocumentLoad = { ...IDLE, status: "loading" };

/** The open site, its brand and its agent-section links, refetched whenever `reloadNonce` moves. A
 * reload of the SAME document keeps the previous load on screen until the new one lands (the web
 * lane's quiet swap); the brand is read once per document. */
export function useSiteDocument({
  documentId,
  reloadNonce,
  repository,
}: {
  documentId: string | null;
  reloadNonce: number;
  repository: SiteRepository;
}): SiteDocumentLoad {
  const [state, setState] = useState<SiteDocumentLoad & { forDocumentId: string | null }>({ ...IDLE, forDocumentId: null });
  const brandRef = useRef<{ brand: BrandData; documentId: string } | null>(null);
  useEffect(() => {
    if (!documentId) return;
    let live = true;
    void (async () => {
      try {
        const loaded = await repository.get(documentId);
        const cachedBrand = brandRef.current?.documentId === documentId ? brandRef.current.brand : null;
        const [brand, links] = await Promise.all([
          cachedBrand ? Promise.resolve(cachedBrand) : repository.getBrand(documentId),
          Object.keys(loaded.site.agent_sections).length > 0 ? repository.sectionLinks(documentId) : Promise.resolve([]),
        ]);
        if (!live) return;
        brandRef.current = { brand, documentId };
        setState({ brand, error: null, forDocumentId: documentId, links, loaded, loadedAt: Date.now(), status: "ready" });
      } catch (error) {
        if (!live) return;
        setState({ ...IDLE, error: error instanceof Error ? error.message : String(error), forDocumentId: documentId, status: "error" });
      }
    })();
    return () => {
      live = false;
    };
  }, [documentId, reloadNonce, repository]);
  if (!documentId) return IDLE;
  if (state.forDocumentId !== documentId) return LOADING;
  return state;
}
```

`apps/frontend/src/features/site-editor/hooks/use-site-frame-host.ts`:
```ts
"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  acceptFrameMessage,
  appToFrame,
  type AppToFramePayloads,
  type AppToFrameType,
  type FrameToAppMessage,
} from "@clue/site-kit/editor-protocol";

export interface SiteFrameHost {
  /** Bumps each time the frame boots (posts `ready`); 0 until the first boot. */
  boot: number;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  post: <T extends AppToFrameType>(type: T, payload: AppToFramePayloads[T], documentId: string) => void;
  src: string | null;
}

/** One editor frame per editor origin. A fresh nonce rides in the URL fragment (never sent to a
 * server); every inbound message is checked by `acceptFrameMessage` (exact origin, the iframe's own
 * window, the nonce, the document the last `init` named); every outbound message is posted to the
 * exact editor origin — never "*". */
export function useSiteFrameHost({
  editorOrigin,
  onMessage,
}: {
  editorOrigin: string | null;
  onMessage: (message: FrameToAppMessage) => void;
}): SiteFrameHost {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const nonce = useMemo(() => (editorOrigin ? globalThis.crypto.randomUUID() : null), [editorOrigin]);
  const documentIdRef = useRef<string | null>(null);
  const [boot, setBoot] = useState(0);
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  useEffect(() => {
    if (!editorOrigin || !nonce) return;
    const listener = (event: MessageEvent) => {
      const message = acceptFrameMessage(
        { data: event.data, origin: event.origin, source: event.source },
        { documentId: documentIdRef.current, editorOrigin, nonce, source: iframeRef.current?.contentWindow ?? null },
      );
      if (!message) return;
      if (message.type === "ready") {
        documentIdRef.current = null;
        setBoot((count) => count + 1);
      }
      onMessageRef.current(message);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [editorOrigin, nonce]);

  const post = useCallback(
    <T extends AppToFrameType>(type: T, payload: AppToFramePayloads[T], documentId: string) => {
      const target = iframeRef.current?.contentWindow;
      if (!editorOrigin || !nonce || !target) return;
      if (type === "init") documentIdRef.current = documentId;
      target.postMessage(appToFrame(type, payload, { documentId, nonce }), editorOrigin);
    },
    [editorOrigin, nonce],
  );

  return { boot, iframeRef, post, src: editorOrigin && nonce ? `${editorOrigin}/#n=${nonce}` : null };
}
```

- [ ] **Step 6: Write the editing session.**

`apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
```ts
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FrameToAppMessage } from "@clue/site-kit/editor-protocol";
import { canonicalJson } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import { httpSiteRepository, type SiteRepository } from "../data/site.repository";
import { siteCanvasState } from "../model/site-canvas-state";
import {
  acceptsFrameEdits,
  frameSyncFor,
  initialRoute,
  linksFresh,
  siteFrameMode,
  siteInitKey,
} from "../model/site-frame-sync";
import { siteStageMounted, type SiteStageBinding } from "../model/site-stage";
import { useSiteDocument } from "./use-site-document";
import { useSiteEditorOrigin } from "./use-site-editor-origin";
import { useSiteFrameHost, type SiteFrameHost } from "./use-site-frame-host";
import { useSiteSaves, type SiteSaves } from "./use-site-saves";

const DEFAULT_REPOSITORY = httpSiteRepository();

/** The app's copy of the site (ruling: the app holds the site JSON and is the only side that saves). */
export interface AppSite {
  documentId: string;
  site: SiteDocument;
  version: number;
}

export interface SiteEditingSession {
  activeDocumentId: string | null;
  post: SiteFrameHost["post"];
  reload: () => void;
  reloadNonce: number;
  route: string;
  saves: SiteSaves;
  setSite: (site: SiteDocument) => void;
  site: SiteDocument | null;
  stage: SiteStageBinding;
  version: number | null;
}

export function useSiteEditingSession({
  activeArtifactId,
  documentIds,
  editing,
  enabled,
  locked,
  repository = DEFAULT_REPOSITORY,
  warm,
}: {
  activeArtifactId: string | null;
  documentIds: Record<string, string> | undefined;
  editing: boolean;
  enabled: boolean;
  locked: boolean;
  repository?: SiteRepository;
  warm: boolean;
}): SiteEditingSession {
  const activeDocumentId = enabled && activeArtifactId ? (documentIds?.[activeArtifactId] ?? null) : null;
  const origin = useSiteEditorOrigin(enabled || warm);
  const [reloadNonce, setReloadNonce] = useState(0);
  const reload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);
  const load = useSiteDocument({ documentId: activeDocumentId, reloadNonce, repository });
  const saves = useSiteSaves({ documentId: activeDocumentId, lockNote: AGENT_RUN_LOCK_NOTE, onReload: reload, repository });

  // Adopt each load as the app's copy: React's adjust-state-on-prop-change pattern, never a setState
  // inside an effect (this repo's react-hooks rule).
  const [appSite, setAppSite] = useState<AppSite | null>(null);
  const [adopted, setAdopted] = useState(load.loaded);
  if (load.loaded !== adopted) {
    setAdopted(load.loaded);
    if (load.loaded) {
      setAppSite({ documentId: load.loaded.documentId, site: load.loaded.site, version: load.loaded.version });
    }
  }
  const currentSite = appSite && appSite.documentId === activeDocumentId ? appSite : null;
  const adopt = saves.adopt;
  useEffect(() => {
    if (load.loaded) adopt(load.loaded);
  }, [adopt, load.loaded]);

  const [routeState, setRouteState] = useState<{ documentId: string; route: string } | null>(null);
  const route = routeState && routeState.documentId === activeDocumentId ? routeState.route : "/";
  const [shownDocumentId, setShownDocumentId] = useState<string | null>(null);
  const [frameError, setFrameError] = useState<{ documentId: string; message: string } | null>(null);
  const mode = siteFrameMode({ editing, locked });

  const latest = useRef({ currentSite, editing, locked, save: saves.save });
  useEffect(() => {
    latest.current = { currentSite, editing, locked, save: saves.save };
  });

  const handleFrameMessage = useCallback((message: FrameToAppMessage) => {
    const now = latest.current;
    switch (message.type) {
      case "navigated":
        setShownDocumentId(message.documentId);
        setRouteState({ documentId: message.documentId, route: message.payload.route });
        setFrameError(null);
        return;
      case "changed": {
        const current = now.currentSite;
        if (!current || message.documentId !== current.documentId) return;
        // Review focus 5: an edit outside edit mode, or under the agent-run lock, is never saved.
        if (!acceptsFrameEdits({ editing: now.editing, locked: now.locked })) return;
        if (canonicalJson(message.payload.site) === canonicalJson(current.site)) return;
        setAppSite({ ...current, site: message.payload.site });
        now.save(message.payload.site);
        return;
      }
      case "error":
        setFrameError({ documentId: message.documentId, message: message.payload.message || message.payload.code });
        return;
      default:
        // selected / deselected / annotate / request_asset / shortcut: Tasks 9-12 add their cases here.
        return;
    }
  }, []);
  const frame = useSiteFrameHost({ editorOrigin: origin.origin, onMessage: handleFrameMessage });
  const { boot, post } = frame;

  // Keep the frame in step: init for a new document, new agent sections or a rebooted frame;
  // replace_site for a new version of the same document (an agent checkpoint, a history step).
  const sent = useRef<{ initKey: string | null; version: number | null }>({ initKey: null, version: null });
  useEffect(() => {
    if (!activeDocumentId || !currentSite || load.status !== "ready" || !load.brand || boot === 0) return;
    const initKey = siteInitKey(activeDocumentId, currentSite.site, boot);
    const sync = frameSyncFor({
      frameReady: true,
      initKey,
      sentInitKey: sent.current.initKey,
      sentVersion: sent.current.version,
      version: currentSite.version,
    });
    if (sync.kind === "init") {
      // Review focus 4: never hand the frame links that may already have expired.
      if (!linksFresh(load.loadedAt, Date.now(), load.links.length)) {
        reload();
        return;
      }
      sent.current = { initKey, version: currentSite.version };
      post(
        "init",
        {
          brand: load.brand,
          device: "Desktop",
          mode,
          route: initialRoute(currentSite.site, route),
          sections: load.links,
          site: currentSite.site,
        },
        activeDocumentId,
      );
      return;
    }
    if (sync.kind === "replace") {
      sent.current = { ...sent.current, version: sync.version };
      post("replace_site", { site: currentSite.site, version: sync.version }, activeDocumentId);
    }
  }, [activeDocumentId, boot, currentSite, load.brand, load.links, load.loadedAt, load.status, mode, post, reload, route]);

  // Edit / preview, sent once per change after the frame shows this document.
  const sentMode = useRef<string | null>(null);
  useEffect(() => {
    if (!activeDocumentId || shownDocumentId !== activeDocumentId) return;
    const key = `${activeDocumentId}|${boot}|${mode}`;
    if (sentMode.current === key) return;
    sentMode.current = key;
    post("set_mode", { mode }, activeDocumentId);
  }, [activeDocumentId, boot, mode, post, shownDocumentId]);

  const setSite = useCallback(
    (site: SiteDocument) => {
      setAppSite((previous) => (previous && previous.documentId === activeDocumentId ? { ...previous, site } : previous));
    },
    [activeDocumentId],
  );

  const canvas = siteCanvasState({
    documentId: activeDocumentId,
    editorOrigin: origin.origin,
    editorOriginError: origin.error,
    editorOriginLoaded: origin.loaded,
    frameError: frameError && frameError.documentId === activeDocumentId ? frameError.message : null,
    frameReady: boot > 0,
    loadError: load.error,
    loadStatus: load.status,
    shownDocumentId,
    site: currentSite?.site ?? null,
  });

  return {
    activeDocumentId,
    post,
    reload,
    reloadNonce,
    route,
    saves,
    setSite,
    site: currentSite?.site ?? null,
    stage: {
      canvas: { errorMessage: canvas.message, iframeRef: frame.iframeRef, renderKind: canvas.kind, src: frame.src },
      mounted: siteStageMounted({ editorOrigin: origin.origin, enabled, warm }),
    },
    version: currentSite?.version ?? null,
  };
}
```

- [ ] **Step 7: Share the web canvas's three states.**

`apps/frontend/src/features/design-editor/components/canvas-states.tsx`:
```tsx
import styles from "./web-artifact-canvas.module.css";

/** The website canvases' three designed states (W2.1), shared by the web and the site canvas. */
export function CanvasLoadingState() {
  return (
    <div className={styles.stateFrame} role="status">
      <p className={styles.stateHint}>Loading preview…</p>
    </div>
  );
}

export function CanvasErrorState({ message }: { message: string }) {
  return (
    <div className={styles.stateFrame} role="alert">
      <p className={styles.stateTitle}>Preview failed</p>
      <p className={styles.stateHint}>{message}</p>
    </div>
  );
}

export function CanvasEmptyState() {
  return (
    <div className={styles.stateFrame}>
      <p className={styles.stateTitle}>Your website will render here</p>
      <p className={styles.stateHint}>Describe what you want in the chat and the agent will build it.</p>
    </div>
  );
}
```

In `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx`, add `import { CanvasEmptyState, CanvasErrorState, CanvasLoadingState } from "./canvas-states";` and replace the three trailing state branches (the `if (state.kind === "error") { return (…) }`, the `if (state.kind === "loading") { return (…) }` and the final `return (<div className={styles.stateFrame}>…</div>);`) with:
```tsx
  if (state.kind === "error") return <CanvasErrorState message={state.message} />;
  if (state.kind === "loading") return <CanvasLoadingState />;
  return <CanvasEmptyState />;
```
The rendered markup is byte-identical to what it replaced.

`apps/frontend/src/features/design-editor/components/site-artifact-canvas.tsx`:
```tsx
"use client";

import { useEffect, useRef } from "react";
import type { SiteCanvasBinding } from "@/features/site-editor/model/site-stage";
import type { VeilRenderKind } from "../adapter/generating-veil";
import { CanvasEmptyState, CanvasErrorState, CanvasLoadingState } from "./canvas-states";
import styles from "./web-artifact-canvas.module.css";

/**
 * The site lane's canvas (D2): ONE iframe onto the workspace's editor domain, where agent code runs
 * away from the marketer's session. It stays mounted while hidden (display: none keeps the frame and
 * its state; moving an iframe in the DOM would reload it), so the frame is warm. The states are the
 * web canvas's own three. No top navigation, no popups, no referrer.
 */
export function SiteArtifactCanvas({
  binding,
  onRenderKindChange,
}: {
  binding: SiteCanvasBinding;
  /** Present only while this canvas is the one on screen (the stage's generating veil reads it). */
  onRenderKindChange?: (kind: VeilRenderKind) => void;
}) {
  const reporting = onRenderKindChange !== undefined;
  const onRenderKindChangeRef = useRef(onRenderKindChange);
  useEffect(() => {
    onRenderKindChangeRef.current = onRenderKindChange;
  });
  useEffect(() => {
    if (reporting) onRenderKindChangeRef.current?.(binding.renderKind);
  }, [binding.renderKind, reporting]);

  return (
    <>
      {binding.src ? (
        <iframe
          className={styles.frame}
          ref={binding.iframeRef}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin"
          src={binding.src}
          style={binding.renderKind === "ready" ? undefined : { display: "none" }}
          title="Website editor"
        />
      ) : null}
      {binding.renderKind === "loading" ? <CanvasLoadingState /> : null}
      {binding.renderKind === "error" ? <CanvasErrorState message={binding.errorMessage ?? ""} /> : null}
      {binding.renderKind === "empty" ? <CanvasEmptyState /> : null}
    </>
  );
}
```

- [ ] **Step 8: Mount the persistent site stage.**

In `apps/frontend/src/features/chat-shell/components/chat-shell.module.css`, add directly after the `.webCanvasMobile { width: 375px; }` rule:
```css
/* Lane C (sites): the persistent site stage keeps its editor iframe mounted while hidden, so the
   frame stays warm. `.outputStage`/`.webOutputStage` set `display`, which would beat `hidden`. */
.siteStage[hidden] {
  display: none;
}
```

In `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`:
- add the imports:
```tsx
import { SiteArtifactCanvas } from "@/features/design-editor/components/site-artifact-canvas";
import type { SiteStageBinding } from "@/features/site-editor/model/site-stage";
```
- add `site,` to the destructured props, and to the props type (next to `overlay`):
```tsx
  /** Lane C: the site editor's persistent stage (the warm frame); absent on routes without sites. */
  site?: SiteStageBinding | null;
```
- directly after `const showingArtifact = surface === "artifact" && artifactKind !== null;` add:
```tsx
  // A site shows the PERSISTENT site stage below instead of the ordinary output stage, so its
  // editor frame is never remounted by a tab or surface switch.
  const siteFrameShown = showingArtifact && artifactKind === "site" && Boolean(site?.mounted);
```
- wrap the existing `<div className={`${styles.outputStage} …`}> … </div>` (the one directly after `<ArtifactHeader … />`) in `{siteFrameShown ? null : ( … )}`;
- directly after the closing `) : null}` of the `{showingArtifact ? ( <> … </> ) : null}` block, add:
```tsx
      {site?.mounted ? (
        <div
          className={`${styles.outputStage} ${styles.webOutputStage} ${styles.siteStage}`}
          hidden={!siteFrameShown}
        >
          <div aria-label="Web output canvas" className={webCanvasClass}>
            <SiteArtifactCanvas
              binding={site.canvas}
              onRenderKindChange={siteFrameShown ? setRenderKind : undefined}
            />
            <WebsiteGeneratingVeil active={siteFrameShown && veilActive} />
            <GeneratingGlow active={siteFrameShown && veilActive} />
          </div>
        </div>
      ) : null}
```

- [ ] **Step 9: Wire the chats route.**

In `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`:
- add `import { useSiteEditingSession } from "@/features/site-editor/hooks/use-site-editing-session";`;
- directly after `const sceneLocked = agentRunLock.locked && shell.artifactKind === "ad";` add:
```tsx
  // Ruling (Wave 2): the agent-run lock applies to sites too — the same derivation, the site lane.
  const siteLocked = agentRunLock.locked && shell.artifactKind === "site";
```
- directly after the `const sceneSession = useSceneEditingSession({ … });` call add:
```tsx
  // Lane C: the site lane's session. Warm (the editor frame mounted ahead of time) once the project
  // has a site or this thread has an open design leg that may birth one.
  const siteSession = useSiteEditingSession({
    activeArtifactId: shell.activeArtifactId,
    documentIds,
    editing: shell.editing,
    enabled: shell.artifactKind === "site",
    locked: siteLocked,
    warm: feedArtifacts.some((artifact) => artifact.documentKind === "site") || chat.designLegOpen,
  });
```
- replace `session.activeDocumentId ?? sceneSession.activeDocumentId;` (the `activeDocumentId` constant) with `session.activeDocumentId ?? sceneSession.activeDocumentId ?? siteSession.activeDocumentId;`;
- in the canvas-revision effect, add `const reloadSiteCanvas = siteSession.reload;` beside `reloadSceneCanvas`, call `reloadSiteCanvas();` after `reloadSceneCanvas();`, and add `reloadSiteCanvas` to that effect's dependency array; do the same in `onArtifactRenamed` (call it, add it to the `useCallback` dependencies);
- on `<ArtifactStage …>`: replace `canvasReloadToken={session.reloadNonce + sceneSession.reloadNonce}` with `canvasReloadToken={session.reloadNonce + sceneSession.reloadNonce + siteSession.reloadNonce}`, replace `editDisabled={sceneLocked && !shell.editing}` with `editDisabled={(sceneLocked || siteLocked) && !shell.editing}`, and add `site={siteSession.stage}`.

- [ ] **Step 10: Wire the artifact route (the document-scoped lock).**

In `apps/frontend/src/features/chat-shell/components/editor-surface.tsx`:
- add `import { useSiteEditingSession } from "@/features/site-editor/hooks/use-site-editing-session";`;
- replace
```tsx
  const sceneDocumentId =
    controller.artifactKind === "ad" && controller.activeArtifactId
      ? (documentIds?.[controller.activeArtifactId] ?? null)
      : null;
  const agentRun = useDocumentAgentRun({
    documentId: sceneDocumentId,
    enabled: controller.artifactKind === "ad",
  });
  const sceneLocked = agentRun.active;
```
with
```tsx
  // The ad lane's document-scoped lock (R1), extended to sites (Wave 2 ruling): one read, keyed on
  // whichever locked kind is open.
  const lockedKind = controller.artifactKind === "ad" || controller.artifactKind === "site";
  const lockDocumentId =
    lockedKind && controller.activeArtifactId
      ? (documentIds?.[controller.activeArtifactId] ?? null)
      : null;
  const agentRun = useDocumentAgentRun({ documentId: lockDocumentId, enabled: lockedKind });
  const sceneLocked = controller.artifactKind === "ad" && agentRun.active;
  const siteLocked = controller.artifactKind === "site" && agentRun.active;
```
- after the `const sceneSession = useSceneEditingSession({ … });` call add:
```tsx
  const siteSession = useSiteEditingSession({
    activeArtifactId: controller.activeArtifactId,
    documentIds,
    editing: controller.editing,
    enabled: controller.artifactKind === "site",
    locked: siteLocked,
    warm: (artifacts ?? []).some((artifact) => artifact.documentKind === "site"),
  });
```
- replace `session.activeDocumentId ?? sceneSession.activeDocumentId;` with `session.activeDocumentId ?? sceneSession.activeDocumentId ?? siteSession.activeDocumentId;`;
- in `onArtifactRenamed` add `const reloadSiteCanvas = siteSession.reload;` beside the other two, call it, and add it to the dependencies;
- on `<ArtifactStage …>`: replace `session.reloadNonce + sceneSession.reloadNonce + agentRun.reloadNonce` with `session.reloadNonce + sceneSession.reloadNonce + siteSession.reloadNonce + agentRun.reloadNonce`, replace `editDisabled={sceneLocked && !controller.editing}` with `editDisabled={(sceneLocked || siteLocked) && !controller.editing}`, and add `site={siteSession.stage}`.

- [ ] **Step 11: Run the whole frontend suite.**

Run: `cd apps/frontend && npm test 2>&1 | tail -6`
Expected: `# fail 0`.

- [ ] **Step 12: Run the frontend check gate.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.

- [ ] **Step 13: Check that web and ad artifacts are unchanged (no editor domain configured yet).**

Start the trenton stack (`./scripts/dev_stack_trenton.sh up`, DEV_STACK.md), sign in with the dev login, open a project with a web artifact and an ad artifact, and confirm: both render exactly as before; the browser devtools Network panel shows `GET /api/clue/site-editor/session` answering `{"data":{"editorOrigin":null}}` only when the project has an open design leg; no iframe to `*.editor.localhost` exists in the DOM. Stop the stack afterwards (`./scripts/dev_stack_trenton.sh down`). The live site walk is Task 15 Step 9 (it needs Lane A/B's K1–K4 routes).

- [ ] **Step 14: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/design-editor/components apps/frontend/src/features/chat-shell/components
git commit -m "site editor: the persistent warm site stage, the Contract 6 frame host and the site editing session (init / replace_site / set_mode, edits saved only while editing and unlocked)"
```

---

### Task 9: C5 — fields and Layers in the app's dock (founder ruling: fields in the app)

The frame describes the selected section's fields as data (`selected {route, componentId, componentType, fields, props}`); the app draws them in the designed dock with the inspector primitives — the precedent is the schema-driven custom-component props form (`web-inspector.tsx:1145-1188`) — and every committed value goes back as `set_props` to the frame and as one save. Values are always read from the **app's** copy of the site, never from the message (the app holds the site JSON). Layers are computed from that same copy: the header, the page's sections in order, the footer. Selecting a layer row sends `select`; the frame selects it in Puck and answers with `selected`. When the header or footer is selected (a click on it in the canvas, or its layer row), the dock shows the shell's fields.

The dock replaces the conversation while editing a site, exactly like the web and ad docks (ruling R6), with the composer still visible.

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-layers.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/site-editor/model/site-selection.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/chat-shell/components/site-inspector.tsx`
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (selection, commit, layers, `inspector`)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (the `site-inspector` dock branch)
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` (the dock on the artifact route)

**Interfaces:**
- Consumes: Task 4 (`componentProps`, `setAtPath`, `withComponentProps`, `getAtPath`, `FieldDescription`, `SHELL_TARGET`), Task 8 (`useSiteEditingSession` internals: `currentSite`, `setAppSite`, `post`, `saves`, `load.brand`, `route`, `editing`, `locked`, `handleFrameMessage`), the inspector primitives (`InspectorHeader`, `InspectorSection`, `InspectorField`, `InspectorInput`, `InspectorTextArea`, `InspectorSelect`, `InspectorLayerRow`).
- Produces:
  - `model/site-layers.ts`: `interface SiteLayerRow { active: boolean; componentId: string; icon: "div" | "layout-template"; key: string; label: string; target: string }`, `cloneLabelsOf(brand: BrandData | null): Record<string, string>`, `componentLabel(type, props, cloneLabels): string`, `siteLayerRows(input: { cloneLabels; route; selection: { target: string; componentId: string } | null; site: SiteDocument | null }): SiteLayerRow[]`.
  - `model/site-selection.ts`: `interface SiteSelection { componentId; componentType; documentId; fields: FieldDescription[]; target: string }`, `interface SiteInspectorBinding { disabled; error; fields: readonly FieldDescription[] | null; layers: readonly SiteLayerRow[]; note; onCommit(name: string, value: unknown): void; onSelectLayer(row: SiteLayerRow): void; selectionKey: string; title: string; values: Record<string, unknown> | null }`, `commitFieldEdit(site, selection, name, value): { site: SiteDocument; props: Record<string, unknown> } | null`, `siteInspectorTitle(site, route, selectedRow): string`.
  - `SiteEditingSession.inspector: SiteInspectorBinding` and `SiteEditingSession.selection: SiteSelection | null` (the active selection: null outside edit mode).
  - `SiteInspector({ binding, renderImageField? })` with `type SiteImageFieldRenderer = (field: FieldDescription, path: string, value: string) => ReactNode` (Task 10 passes it).

- [ ] **Step 1: Write the failing model tests.**

`apps/frontend/src/features/site-editor/model/site-layers.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "@clue/site-kit";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { cloneLabelsOf, componentLabel, siteLayerRows } from "./site-layers";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Garner for SCSD" } },
      content: [
        { type: "ClonedSection", props: { id: "hero", fragmentId: "frag_95041c54da629d99" } },
        { type: "StatsBand", props: { id: "proof", heading: "7.4%" } },
        { type: "AnalysisSteps", props: { id: "steps" } },
      ],
    },
  },
  shell: { header: { id: "header" }, footer: { id: "footer" } },
  agent_sections: { AnalysisSteps: "a".repeat(64) },
});
const cloneLabels = { frag_95041c54da629d99: "Hero — Top Providers. Bottom line results." };

test("Layers list the header, the page's sections in order, then the footer", () => {
  assert.deepEqual(
    siteLayerRows({ cloneLabels, route: "/", selection: null, site }).map((row) => [row.label, row.target, row.componentId, row.icon]),
    [
      ["Header", "shell", "header", "div"],
      ["Hero — Top Providers. Bottom line results.", "/", "hero", "layout-template"],
      ["Stats band", "/", "proof", "layout-template"],
      ["Analysis steps", "/", "steps", "layout-template"],
      ["Footer", "shell", "footer", "div"],
    ],
  );
});

test("the selected row is active; a site without a shell has no header or footer rows", () => {
  const rows = siteLayerRows({ cloneLabels, route: "/", selection: { componentId: "proof", target: "/" }, site });
  assert.deepEqual(rows.filter((row) => row.active).map((row) => row.componentId), ["proof"]);
  const header = siteLayerRows({ cloneLabels, route: "/", selection: { componentId: "header", target: "shell" }, site });
  assert.deepEqual(header.filter((row) => row.active).map((row) => row.key), ["shell#header"]);
  assert.equal(siteLayerRows({ cloneLabels, route: "/", selection: null, site: { ...site, shell: null } }).length, 3);
  assert.deepEqual(siteLayerRows({ cloneLabels, route: "/gone", selection: null, site }), []);
});

test("a section the brand no longer knows is just a Section — the marketer never sees 'clone'", () => {
  assert.equal(componentLabel("ClonedSection", { fragmentId: "frag_gone" }, cloneLabels), "Section");
  assert.equal(componentLabel("CtaBand", { id: "cta" }, cloneLabels), "Call to action band");
});

test("clone labels come from the brand", () => {
  const brand = { clones: { frag_x: { id: "frag_x", label: "Hero — X" } } } as unknown as BrandData;
  assert.deepEqual(cloneLabelsOf(brand), { frag_x: "Hero — X" });
  assert.deepEqual(cloneLabelsOf(null), {});
});
```

`apps/frontend/src/features/site-editor/model/site-selection.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { componentProps } from "@clue/site-kit/editor-site";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { commitFieldEdit, siteInspectorTitle } from "./site-selection";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Garner for SCSD" } },
      content: [{ type: "StatsBand", props: { id: "proof", heading: "7.4%", stats: [{ value: "1" }, { value: "2" }] } }],
    },
    "/analysis": { root: { props: {} }, content: [] },
  },
  shell: { header: { id: "header", preparedFor: "SCSD" }, footer: { id: "footer", legal: "©" } },
  agent_sections: {},
});

test("a field commit writes the prop at its path and keeps the component id", () => {
  const edit = commitFieldEdit(site, { componentId: "proof", target: "/" }, "heading", "8%");
  assert.equal(edit?.props.heading, "8%");
  assert.equal(edit?.props.id, "proof");
  assert.equal(componentProps(edit!.site, "/", "proof")?.heading, "8%");
});

test("a repeating item's field commits at its index", () => {
  const edit = commitFieldEdit(site, { componentId: "proof", target: "/" }, "stats.1.value", "22");
  assert.deepEqual(componentProps(edit!.site, "/", "proof")?.stats, [{ value: "1" }, { value: "22" }]);
});

test("a header field commits through the shell target", () => {
  const edit = commitFieldEdit(site, { componentId: "header", target: "shell" }, "preparedFor", "Syracuse City School District");
  assert.equal(componentProps(edit!.site, "shell", "header")?.preparedFor, "Syracuse City School District");
});

test("a commit for a section that is gone changes nothing", () => {
  assert.equal(commitFieldEdit(site, { componentId: "gone", target: "/" }, "heading", "x"), null);
});

test("the dock's title: the selected layer's label, else the page title, else the route", () => {
  const row = { active: true, componentId: "proof", icon: "layout-template" as const, key: "/#proof", label: "Stats band", target: "/" };
  assert.equal(siteInspectorTitle(site, "/", row), "Stats band");
  assert.equal(siteInspectorTitle(site, "/", undefined), "Garner for SCSD");
  assert.equal(siteInspectorTitle(site, "/analysis", undefined), "/analysis");
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-layers.test.ts src/features/site-editor/model/site-selection.test.ts`
Expected: FAIL — `Cannot find module './site-layers'`.

- [ ] **Step 3: Write the models.**

`apps/frontend/src/features/site-editor/model/site-layers.ts`:
```ts
import type { BrandData } from "@clue/site-kit";
import { pageFor } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

/** One Layers row: the header, a page section, or the footer. */
export interface SiteLayerRow {
  active: boolean;
  componentId: string;
  icon: "div" | "layout-template";
  key: string;
  label: string;
  target: string;
}

// site-kit's own section labels (sections.tsx), never its Puck-panel labels "(agent)" / "Cloned section".
const BUILT_IN_LABELS: Readonly<Record<string, string>> = {
  CtaBand: "Call to action band",
  FeatureSplit: "Feature split",
  ProofCard: "Proof card",
  StatsBand: "Stats band",
};

export function cloneLabelsOf(brand: BrandData | null): Record<string, string> {
  if (!brand) return {};
  return Object.fromEntries(Object.values(brand.clones).map((clone) => [clone.id, clone.label]));
}

/** A section's name for the marketer. A cloned section is called by its own label ("Hero — …");
 * the marketer never sees "clone" or "component" (founder ruling). */
export function componentLabel(type: string, props: Record<string, unknown>, cloneLabels: Readonly<Record<string, string>>): string {
  if (type === "ClonedSection") return cloneLabels[String(props.fragmentId ?? "")] || "Section";
  const builtIn = BUILT_IN_LABELS[type];
  if (builtIn) return builtIn;
  const words = type.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function siteLayerRows({
  cloneLabels,
  route,
  selection,
  site,
}: {
  cloneLabels: Readonly<Record<string, string>>;
  route: string;
  selection: { componentId: string; target: string } | null;
  site: SiteDocument | null;
}): SiteLayerRow[] {
  const page = site ? pageFor(site, route) : null;
  if (!site || !page) return [];
  const isActive = (target: string, componentId: string) =>
    selection?.target === target && selection.componentId === componentId;
  const shellRow = (part: "header" | "footer"): SiteLayerRow => ({
    active: isActive(SHELL_TARGET, part),
    componentId: part,
    icon: "div",
    key: `shell#${part}`,
    label: part === "header" ? "Header" : "Footer",
    target: SHELL_TARGET,
  });
  return [
    ...(site.shell ? [shellRow("header")] : []),
    ...page.content.map((item) => ({
      active: isActive(route, item.props.id),
      componentId: item.props.id,
      icon: "layout-template" as const,
      key: `${route}#${item.props.id}`,
      label: componentLabel(item.type, item.props, cloneLabels),
      target: route,
    })),
    ...(site.shell ? [shellRow("footer")] : []),
  ];
}
```

`apps/frontend/src/features/site-editor/model/site-selection.ts`:
```ts
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { componentProps, pageFor, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { SiteLayerRow } from "./site-layers";

/** What the frame said is selected (Contract 6 `selected`), stamped with its document. The values
 * are never taken from the message: the dock reads them from the app's own copy of the site. */
export interface SiteSelection {
  componentId: string;
  componentType: string;
  documentId: string;
  fields: FieldDescription[];
  target: string;
}

/** Everything the dock draws, as data and callbacks (presentation never reaches the session). */
export interface SiteInspectorBinding {
  disabled: boolean;
  error: string | null;
  fields: readonly FieldDescription[] | null;
  layers: readonly SiteLayerRow[];
  note: string | null;
  onCommit: (name: string, value: unknown) => void;
  onSelectLayer: (row: SiteLayerRow) => void;
  /** Remount identity: a new selection starts with fresh drafts and sections. */
  selectionKey: string;
  title: string;
  values: Record<string, unknown> | null;
}

/** One committed field value → the edited site and the component's whole new props. */
export function commitFieldEdit(
  site: SiteDocument,
  selection: { componentId: string; target: string },
  name: string,
  value: unknown,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, selection.target, selection.componentId);
  if (!props) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, setAtPath(props, name, value));
  if (edited === site) return null;
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

export function siteInspectorTitle(site: SiteDocument | null, route: string, selectedRow: SiteLayerRow | undefined): string {
  if (selectedRow) return selectedRow.label;
  const title = site ? pageFor(site, route)?.root.props.title : undefined;
  return title && title.trim() ? title : route;
}
```

- [ ] **Step 4: Run the model tests.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-layers.test.ts src/features/site-editor/model/site-selection.test.ts`
Expected: 9 passing, 0 failing.

- [ ] **Step 5: Add selection, commits and Layers to the session.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
- extend the imports:
```ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { canonicalJson, componentProps } from "@clue/site-kit/editor-site";
import { cloneLabelsOf, siteLayerRows, type SiteLayerRow } from "../model/site-layers";
import {
  commitFieldEdit,
  siteInspectorTitle,
  type SiteInspectorBinding,
  type SiteSelection,
} from "../model/site-selection";
```
- add to `SiteEditingSession`:
```ts
  inspector: SiteInspectorBinding;
  /** The active selection (null outside edit mode or for another document). */
  selection: SiteSelection | null;
```
- directly after `const mode = siteFrameMode({ editing, locked });` add:
```ts
  const [selection, setSelection] = useState<SiteSelection | null>(null);
```
- in `handleFrameMessage`'s switch, add before `default:`:
```ts
      case "selected":
        setSelection({
          componentId: message.payload.componentId,
          componentType: message.payload.componentType,
          documentId: message.documentId,
          fields: message.payload.fields,
          target: message.payload.route,
        });
        return;
      case "deselected":
        setSelection(null);
        return;
```
- directly before `const canvas = siteCanvasState({` add:
```ts
  // The dock (C5): the selected section's fields over the app's own copy of the site, and Layers.
  const activeSelection = editing && selection && selection.documentId === activeDocumentId ? selection : null;
  const cloneLabels = useMemo(() => cloneLabelsOf(load.brand), [load.brand]);
  const layers = siteLayerRows({ cloneLabels, route, selection: activeSelection, site: currentSite?.site ?? null });
  const values =
    activeSelection && currentSite ? componentProps(currentSite.site, activeSelection.target, activeSelection.componentId) : null;
  const save = saves.save;
  const commitField = useCallback(
    (name: string, value: unknown) => {
      if (!activeSelection || !currentSite || !activeDocumentId || !acceptsFrameEdits({ editing, locked })) return;
      const edit = commitFieldEdit(currentSite.site, activeSelection, name, value);
      if (!edit) return;
      setAppSite({ ...currentSite, site: edit.site });
      post("set_props", { componentId: activeSelection.componentId, props: edit.props, route: activeSelection.target }, activeDocumentId);
      save(edit.site, `inspector: edit ${name}`);
    },
    [activeDocumentId, activeSelection, currentSite, editing, locked, post, save],
  );
  const selectLayer = useCallback(
    (row: SiteLayerRow) => {
      if (!activeDocumentId || !editing) return;
      post("select", { componentId: row.componentId, route: row.target }, activeDocumentId);
    },
    [activeDocumentId, editing, post],
  );
  const inspector: SiteInspectorBinding = {
    disabled: locked,
    error: saves.error,
    fields: activeSelection?.fields ?? null,
    layers,
    note: saves.note,
    onCommit: commitField,
    onSelectLayer: selectLayer,
    selectionKey: activeSelection ? `${activeSelection.target}#${activeSelection.componentId}` : `page:${route}`,
    title: siteInspectorTitle(currentSite?.site ?? null, route, layers.find((row) => row.active)),
    values,
  };
```
- add `inspector,` and `selection: activeSelection,` to the returned object.

- [ ] **Step 6: Write the dock panel.**

`apps/frontend/src/features/chat-shell/components/site-inspector.tsx`:
```tsx
"use client";

import { useState, type ReactNode } from "react";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { getAtPath } from "@clue/site-kit/editor-site";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import {
  InspectorField,
  InspectorHeader,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
  InspectorTextArea,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";

export type SiteImageFieldRenderer = (field: FieldDescription, path: string, value: string) => ReactNode;

/**
 * Lane C / C5 (founder ruling: fields in the app): the site's dock. The frame describes the selected
 * section's fields as data (Contract 6 `FieldDescription`); this panel draws them with the existing
 * inspector primitives — the precedent is the custom-component props form in web-inspector.tsx — and
 * hands each committed value to the session (`set_props` to the frame, then one save). Layers come
 * from the app's own copy of the site. While the agent-run lock holds, the whole subtree is disabled
 * by a `display: contents` fieldset, exactly as the props form does it.
 */
export function SiteInspector({
  binding,
  renderImageField,
}: {
  binding: SiteInspectorBinding;
  renderImageField?: SiteImageFieldRenderer;
}) {
  const [contentOpen, setContentOpen] = useState(true);
  const [layersOpen, setLayersOpen] = useState(true);
  return (
    <aside aria-label="Website inspector" className={styles.inspector}>
      <div className={styles.inspectorRail}>
        <InspectorHeader elementActions={false} title={binding.title} />
        {binding.note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {binding.note}
          </p>
        ) : null}
        {binding.error ? (
          <p className={styles.inspectorStatusError} role="alert">
            {binding.error}
          </p>
        ) : null}
        {binding.fields ? (
          // DESIGN REVIEW (DR4): the section label for a selected site section.
          <InspectorSection label="Content" onOpenChange={setContentOpen} open={contentOpen}>
            <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
              {binding.fields.length === 0 ? (
                <p className={styles.inspectorFieldLabel}>This section has nothing to edit here.</p>
              ) : (
                binding.fields.map((field) => (
                  <SiteFieldControl
                    disabled={binding.disabled}
                    field={field}
                    key={field.name}
                    onCommit={binding.onCommit}
                    path={field.name}
                    renderImageField={renderImageField}
                    values={binding.values}
                  />
                ))
              )}
            </fieldset>
          </InspectorSection>
        ) : null}
        <InspectorSection label="Layers" onOpenChange={setLayersOpen} open={layersOpen}>
          <div className={styles.layerList}>
            {binding.layers.map((row) => (
              <InspectorLayerRow
                active={row.active}
                icon={row.icon}
                key={row.key}
                label={row.label}
                onClick={() => binding.onSelectLayer(row)}
              />
            ))}
          </div>
        </InspectorSection>
      </div>
    </aside>
  );
}

function textOf(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

function SiteFieldControl({
  disabled,
  field,
  onCommit,
  path,
  renderImageField,
  values,
}: {
  disabled: boolean;
  field: FieldDescription;
  onCommit: (name: string, value: unknown) => void;
  path: string;
  renderImageField?: SiteImageFieldRenderer;
  values: Record<string, unknown> | null;
}) {
  const value = getAtPath(values, path);
  switch (field.kind) {
    case "text":
    case "link":
      return (
        <InspectorField label={field.label}>
          <InspectorInput ariaLabel={field.label} disabled={disabled} onCommitValue={(next) => onCommit(path, next)} value={textOf(value)} />
        </InspectorField>
      );
    case "textarea":
      return (
        <InspectorField label={field.label}>
          <InspectorTextArea ariaLabel={field.label} disabled={disabled} onCommitValue={(next) => onCommit(path, next)} value={textOf(value)} />
        </InspectorField>
      );
    case "number":
      return (
        <InspectorField label={field.label}>
          <InspectorInput
            ariaLabel={field.label}
            disabled={disabled}
            onCommitValue={(next) => {
              const parsed = Number(next);
              if (next.trim() !== "" && Number.isFinite(parsed)) onCommit(path, parsed);
            }}
            value={textOf(value)}
          />
        </InspectorField>
      );
    case "boolean":
      return (
        <label className={styles.checkboxRow}>
          <input
            aria-label={field.label}
            checked={value === true}
            disabled={disabled}
            onChange={(event) => onCommit(path, event.target.checked)}
            type="checkbox"
          />
          <span>{field.label}</span>
        </label>
      );
    case "select": {
      const options = field.options ?? [];
      return (
        <InspectorField label={field.label}>
          <InspectorSelect
            disabled={disabled}
            label={field.label}
            onChange={(label) => {
              const option = options.find((candidate) => candidate.label === label);
              if (option) onCommit(path, option.value);
            }}
            options={options.map((option) => option.label)}
            value={options.find((option) => option.value === value)?.label ?? ""}
          />
        </InspectorField>
      );
    }
    case "image":
      return renderImageField ? (
        renderImageField(field, path, textOf(value))
      ) : (
        <InspectorField label={field.label}>
          <InspectorInput ariaLabel={field.label} readOnly value={textOf(value)} />
        </InspectorField>
      );
    case "list": {
      const items = Array.isArray(value) ? value : [];
      // DESIGN REVIEW (DR6, plan Q2): repeating items are edited in place; adding or removing one
      // waits for a design.
      return (
        <>
          {items.map((_item, index) => (
            <div key={`${path}.${index}`}>
              <p className={styles.inspectorFieldLabel}>{`${field.label} ${index + 1}`}</p>
              {(field.item ?? []).map((child) => (
                <SiteFieldControl
                  disabled={disabled}
                  field={child}
                  key={child.name}
                  onCommit={onCommit}
                  path={`${path}.${index}.${child.name}`}
                  renderImageField={renderImageField}
                  values={values}
                />
              ))}
            </div>
          ))}
        </>
      );
    }
  }
}
```

- [ ] **Step 7: Mount the dock on both routes.**

In `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, add `import { SiteInspector } from "./site-inspector";` and, directly after the `{dockContent === "ad-inspector" ? ( … ) : null}` block, add:
```tsx
          {dockContent === "site-inspector" ? (
            <div className={styles.inspectorDock}>
              <SiteInspector
                // Keyed on the selection only (the web dock's rule): a new selection starts with
                // fresh drafts; a write never remounts the panel.
                binding={siteSession.inspector}
                key={siteSession.inspector.selectionKey}
              />
            </div>
          ) : null}
```

In `apps/frontend/src/features/chat-shell/components/editor-surface.tsx`, add `import { SiteInspector } from "./site-inspector";`, add after `const adInspectorVisible = …;`:
```tsx
  const siteInspectorVisible =
    controller.editing &&
    controller.artifactKind === "site" &&
    siteSession.activeDocumentId !== null;
```
replace `const inspectorVisible = webInspectorVisible || adInspectorVisible;` with `const inspectorVisible = webInspectorVisible || adInspectorVisible || siteInspectorVisible;`, and add directly after the `{adInspectorVisible ? ( … ) : null}` block:
```tsx
      {siteInspectorVisible ? (
        <div className={styles.chatBody}>
          <div className={styles.inspectorDock}>
            <SiteInspector binding={siteSession.inspector} key={siteSession.inspector.selectionKey} />
          </div>
        </div>
      ) : null}
```

- [ ] **Step 8: Run the suite and the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -6 && npm run design-system:build && npm run lint && npm run build`
Expected: `# fail 0`; all three gate commands exit 0.

- [ ] **Step 9: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/chat-shell/components
git commit -m "site editor: fields and Layers in the app's dock — FieldDescriptions drawn with the inspector primitives, set_props back to the frame, one save per commit"
```

---

### Task 10: C6 — images: the asset library and the generate rows for site image fields

A site stores every image as `/asset-store/<sha256>` (Contract 1). An image field in the dock is the designed "Replace image" pill (`InspectorImageUpload` with its Upload / Library menu) followed by the ad inspector's designed generate rows (`AdImageAiRows`, reused as-is through its `SceneImageAiBinding` contract). Picking from the `AssetLibraryPanel`, uploading, generating or accepting an edited image all end the same way: the app writes the url into its copy of the site, sends `insert_asset {route, componentId, prop, url}` to the frame, and saves. A double-click on an image in the canvas makes the frame send `request_asset`, which opens the same library for that field.

The app shows the picture through its own public passthrough (`/api/clue/design-public/asset-store/<digest>`); the frame shows the same bytes through the editor origin's `/asset-store/<digest>` proxy (Task 5).

**Files:**
- Create: `apps/frontend/src/features/site-editor/hooks/site-images.logic.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-images.ts`
- Create: `apps/frontend/src/features/chat-shell/components/site-image-field.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx:663` (export `AdImageAiRows`)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (insert, `request_asset`, `images`, `imageField`)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, `editor-surface.tsx` (image fields, overlay)
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx` (double-click on an image → `request_asset`)

**Interfaces:**
- Consumes: Task 9 (`activeSelection`, `SiteInspector`'s `renderImageField`), Task 4 (`withAssetAt`, `componentProps`, `getAtPath`), the ad lane's pieces: `composeAssetLibrary`, `filterAssetLibrary`, `kitLibraryEntries` (`design-editor/adapter/scene-asset-library.ts`), `SceneAssetLibraryBinding` (`design-editor/hooks/use-scene-asset-library.ts`), `listImageAssets`, `uploadWebAsset` (`design-editor/data/assets.ts`), `generateSceneAsset`, `editSceneAsset` (`design-editor/hooks/use-scene-image-ai.ts`), `REMOVE_BACKGROUND_INSTRUCTION`, `sceneGeneratedAssetLabel`, `SceneImageAiBinding` (`design-editor/adapter/scene-image-ai.ts`), `AssetLibraryPanel`, `InspectorImageUpload`, `AdImageAiRows`.
- Produces:
  - `site-images.logic.ts`: `IMAGE_PLACEHOLDER_SRC`, `SITE_IMAGE_NOT_SAVED`, `interface SiteImageTarget { componentId: string; prop: string; target: string }`, `sameImageTarget(a, b): boolean`, `assetStoreUrlOf(record): string | null`, `appAssetSrc(url: string): string`, `assetIdForUrl(records, url): string | null`, `interface SiteImageAiState`, `EMPTY_SITE_IMAGE_AI`, `createSiteImageAiRunner(readDeps): SiteImageAiRunner` (`generate(target, prompt)`, `edit(target, instruction, transparent?)`, `accept(target): boolean`, `reject()`, `saveAsNew(): boolean`), `siteImageAiBinding(input): SceneImageAiBinding`.
  - `use-site-images.ts`: `interface SiteImageFieldBinding { ai: SceneImageAiBinding; onFileSelect(file: File): Promise<void>; onOpenLibrary(): void; previewSrc: string }`, `interface SiteImages { field(target, value): SiteImageFieldBinding; library: SceneAssetLibraryBinding | null; openLibraryFor(target): void; uploadToLibraryTarget(file: File): Promise<void> }`, `useSiteImages(options): SiteImages`.
  - `SiteEditingSession.images: SiteImages`, `SiteEditingSession.imageField(path: string, value: string): SiteImageFieldBinding | null`.
  - `SiteImageField({ binding, disabled, label })`.

- [ ] **Step 1: Write the failing tests.**

`apps/frontend/src/features/site-editor/hooks/site-images.logic.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";
import {
  EMPTY_SITE_IMAGE_AI,
  IMAGE_PLACEHOLDER_SRC,
  SITE_IMAGE_NOT_SAVED,
  appAssetSrc,
  assetIdForUrl,
  assetStoreUrlOf,
  createSiteImageAiRunner,
  siteImageAiBinding,
  type SiteImageAiDeps,
  type SiteImageAiState,
} from "./site-images.logic";

const A = "a".repeat(64);
const B = "b".repeat(64);
const record = (id: string, digest: string | null, status = "ready") =>
  ({ id, label: id, kind: "raster_image", status, source: { kind: "uploaded" }, media: digest ? { digest: { algorithm: "sha256", value: digest } } : {} }) as unknown as AssetRecord;
const HERO = { componentId: "what", prop: "image", target: "/analysis" };

test("an asset's site url is its sha256 content address, shown in the app through the public passthrough", () => {
  assert.equal(assetStoreUrlOf(record("asset_1", A)), `/asset-store/${A}`);
  assert.equal(assetStoreUrlOf(record("asset_2", null)), null);
  assert.equal(appAssetSrc(`/asset-store/${A}`), `/api/clue/design-public/asset-store/${A}`);
  assert.equal(appAssetSrc(""), IMAGE_PLACEHOLDER_SRC);
  assert.equal(appAssetSrc("https://tracker.example/p.gif"), IMAGE_PLACEHOLDER_SRC);
  assert.equal(assetIdForUrl([record("asset_1", A), record("asset_2", B)], `/asset-store/${B}`), "asset_2");
  assert.equal(assetIdForUrl([record("asset_1", A, "pending")], `/asset-store/${A}`), null);
});

function harness(overrides: Partial<SiteImageAiDeps> = {}) {
  let state: SiteImageAiState = EMPTY_SITE_IMAGE_AI;
  const placed: string[] = [];
  const errors: string[] = [];
  const deps: SiteImageAiDeps = {
    clearMessages: () => undefined,
    currentUrl: () => `/asset-store/${A}`,
    documentId: "doc-1",
    edit: async () => record("asset_edit", B),
    generate: async () => record("asset_gen", B),
    onError: (message) => errors.push(message),
    place: (_target, url) => {
      placed.push(url);
      return true;
    },
    publish: (next) => {
      state = next;
    },
    sourceAssetId: () => "asset_1",
    writable: () => true,
    ...overrides,
  };
  const runner = createSiteImageAiRunner(() => deps);
  return { deps, errors, placed, runner, state: () => state };
}

test("a generated picture is placed straight into the field it was asked for", async () => {
  const h = harness();
  await h.runner.generate(HERO, "a calm clinic reception");
  assert.deepEqual(h.placed, [`/asset-store/${B}`]);
  assert.equal(h.state().generating, false);
});

test("a generation is refused before the spend when the field is not writable", async () => {
  let spent = 0;
  const h = harness({ generate: async () => (spent++, record("asset_gen", B)), writable: () => false });
  await h.runner.generate(HERO, "a calm clinic reception");
  assert.equal(spent, 0);
  assert.deepEqual(h.placed, []);
});

test("a picture paid for on one document is never placed on another", async () => {
  const h = harness();
  const pending = h.runner.generate(HERO, "a calm clinic reception");
  h.deps.documentId = "doc-2";
  await pending;
  assert.deepEqual(h.placed, []);
});

test("a picture without a stored file says so instead of placing a broken url", async () => {
  const h = harness({ generate: async () => record("asset_gen", null) });
  await h.runner.generate(HERO, "x");
  assert.deepEqual(h.errors, [SITE_IMAGE_NOT_SAVED]);
});

test("an edit stages a candidate; accept places it only on its own field; save-as-new notes it", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  assert.equal(h.state().candidate?.record.id, "asset_edit");
  assert.equal(h.runner.accept({ ...HERO, prop: "logo" }), false, "never onto another field");
  assert.equal(h.runner.accept(HERO), true);
  assert.deepEqual(h.placed, [`/asset-store/${B}`]);
  await h.runner.edit(HERO, "again");
  assert.equal(h.runner.saveAsNew(), true);
  assert.equal(h.state().savedNotice?.message, "Saved asset_edit to the asset library.");
});

test("the binding shows a candidate and a notice only on the field they belong to", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  const own = siteImageAiBinding({ ai: h.state(), canEdit: true, documentId: "doc-1", runner: h.runner, target: HERO, url: `/asset-store/${A}` });
  const other = siteImageAiBinding({ ai: h.state(), canEdit: true, documentId: "doc-1", runner: h.runner, target: { ...HERO, prop: "logo" }, url: "" });
  assert.equal(own.candidate?.label, "asset_edit");
  assert.equal(own.beforeSrc, `/api/clue/design-public/asset-store/${A}`);
  assert.equal(own.hasImage, true);
  assert.equal(other.candidate, null);
  assert.equal(other.hasImage, false);
});
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/hooks/site-images.logic.test.ts`
Expected: FAIL — `Cannot find module './site-images.logic'`.

- [ ] **Step 3: Write the image logic.**

`apps/frontend/src/features/site-editor/hooks/site-images.logic.ts`:
```ts
import {
  REMOVE_BACKGROUND_INSTRUCTION,
  sceneGeneratedAssetLabel,
  type SceneImageAiBinding,
} from "@/features/design-editor/adapter/scene-image-ai";
import { DESIGN_PUBLIC_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import type { EditAssetRequest, GenerateAssetRequest } from "@/features/design-editor/engine/scene/assetLibrary";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";

/**
 * Lane C / C6: the site lane's image decisions. The shape is the ad lane's
 * (`use-scene-image-ai.ts`): refuse before you spend, re-check the document after the await, a
 * generation lands at once while an edit is a staged candidate, and a candidate is placed on the
 * field it was made for or nowhere.
 */
export const IMAGE_PLACEHOLDER_SRC = "/icons/chat-shell/inspector/web/image-preview.png";
export const SITE_IMAGE_NOT_SAVED = "That image has no stored file yet.";
const ASSET_STORE_URL = /^\/asset-store\/([0-9a-f]{64})$/;

/** One image field: a prop path on a component (a page section or the shell's header/footer). */
export interface SiteImageTarget {
  componentId: string;
  prop: string;
  target: string;
}

export function sameImageTarget(left: SiteImageTarget, right: SiteImageTarget): boolean {
  return left.target === right.target && left.componentId === right.componentId && left.prop === right.prop;
}

/** Contract 1: an image in a site is `/asset-store/<sha256>` of a blob of this workspace. */
export function assetStoreUrlOf(record: Pick<AssetRecord, "media">): string | null {
  const digest = record.media?.digest;
  if (!digest || !/^sha-?256$/i.test(digest.algorithm) || !/^[0-9a-f]{64}$/.test(digest.value)) return null;
  return `/asset-store/${digest.value}`;
}

/** The app shows a site image through its own headerless passthrough; anything else is the
 * inspector's stock preview (never a foreign url in the app). */
export function appAssetSrc(url: string): string {
  return ASSET_STORE_URL.test(url) ? `${DESIGN_PUBLIC_BFF_PREFIX}${url}` : IMAGE_PLACEHOLDER_SRC;
}

/** The registry asset behind a site url, when it is ready to be edited. */
export function assetIdForUrl(records: readonly AssetRecord[], url: string): string | null {
  const match = ASSET_STORE_URL.exec(url);
  if (!match) return null;
  return records.find((candidate) => candidate.status === "ready" && candidate.media?.digest?.value === match[1])?.id ?? null;
}

export interface SiteImageAiState {
  candidate: { documentId: string; record: AssetRecord; target: SiteImageTarget } | null;
  editing: boolean;
  generating: boolean;
  savedNotice: { documentId: string; message: string; target: SiteImageTarget } | null;
}

export const EMPTY_SITE_IMAGE_AI: SiteImageAiState = { candidate: null, editing: false, generating: false, savedNotice: null };

export interface SiteImageAiDeps {
  clearMessages: () => void;
  currentUrl: (target: SiteImageTarget) => string;
  documentId: string | null;
  edit: (request: EditAssetRequest) => Promise<AssetRecord>;
  generate: (request: GenerateAssetRequest) => Promise<AssetRecord>;
  onError: (message: string) => void;
  place: (target: SiteImageTarget, url: string) => boolean;
  publish: (state: SiteImageAiState) => void;
  sourceAssetId: (url: string) => string | null;
  writable: () => boolean;
}

export interface SiteImageAiRunner {
  accept: (target: SiteImageTarget) => boolean;
  edit: (target: SiteImageTarget, instruction: string, transparentBackground?: boolean) => Promise<void>;
  generate: (target: SiteImageTarget, prompt: string) => Promise<void>;
  reject: () => void;
  saveAsNew: () => boolean;
}

const failureOf = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

export function createSiteImageAiRunner(readDeps: () => SiteImageAiDeps): SiteImageAiRunner {
  let state = EMPTY_SITE_IMAGE_AI;
  const set = (patch: Partial<SiteImageAiState>) => {
    state = { ...state, ...patch };
    readDeps().publish(state);
  };
  return {
    accept(target) {
      const staged = state.candidate;
      const deps = readDeps();
      if (!staged || !sameImageTarget(staged.target, target) || deps.documentId !== staged.documentId || !deps.writable()) {
        return false;
      }
      const url = assetStoreUrlOf(staged.record);
      if (!url) {
        deps.onError(SITE_IMAGE_NOT_SAVED);
        return false;
      }
      deps.clearMessages();
      if (!deps.place(target, url)) return false;
      set({ candidate: null, savedNotice: null });
      return true;
    },
    async edit(target, instruction, transparentBackground) {
      const trimmed = instruction.trim();
      const before = readDeps();
      if (state.generating || state.editing || state.candidate || !trimmed || !before.documentId || !before.writable()) return;
      const source = before.sourceAssetId(before.currentUrl(target));
      if (!source) return;
      const documentId = before.documentId;
      before.clearMessages();
      set({ editing: true, savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.edit({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed, sourceAssetId: source, transparentBackground });
      } catch (cause) {
        before.onError(failureOf(cause));
        return;
      } finally {
        set({ editing: false });
      }
      set({ candidate: { documentId, record, target } });
    },
    async generate(target, prompt) {
      const trimmed = prompt.trim();
      const before = readDeps();
      if (state.generating || state.editing || !trimmed || !before.documentId || !before.writable()) return;
      const documentId = before.documentId;
      before.clearMessages();
      set({ generating: true, savedNotice: null });
      let record: AssetRecord;
      try {
        record = await before.generate({ label: sceneGeneratedAssetLabel(trimmed), prompt: trimmed });
      } catch (cause) {
        before.onError(failureOf(cause));
        return;
      } finally {
        set({ generating: false });
      }
      const after = readDeps();
      // A paid picture is never placed on a document the user is no longer looking at.
      if (after.documentId !== documentId || !after.writable()) return;
      const url = assetStoreUrlOf(record);
      if (!url) {
        after.onError(SITE_IMAGE_NOT_SAVED);
        return;
      }
      after.place(target, url);
    },
    reject() {
      set({ candidate: null, savedNotice: null });
    },
    saveAsNew() {
      const staged = state.candidate;
      if (!staged) return false;
      set({
        candidate: null,
        savedNotice: {
          documentId: staged.documentId,
          message: `Saved ${staged.record.label || staged.record.id} to the asset library.`,
          target: staged.target,
        },
      });
      return true;
    },
  };
}

/** The ad lane's generate rows, driven for one site image field. */
export function siteImageAiBinding({
  ai,
  canEdit,
  documentId,
  runner,
  target,
  url,
}: {
  ai: SiteImageAiState;
  canEdit: boolean;
  documentId: string | null;
  runner: SiteImageAiRunner;
  target: SiteImageTarget;
  url: string;
}): SceneImageAiBinding {
  const candidate =
    ai.candidate && ai.candidate.documentId === documentId && sameImageTarget(ai.candidate.target, target) ? ai.candidate : null;
  const notice =
    ai.savedNotice && ai.savedNotice.documentId === documentId && sameImageTarget(ai.savedNotice.target, target)
      ? ai.savedNotice.message
      : null;
  const candidateUrl = candidate ? assetStoreUrlOf(candidate.record) : null;
  return {
    beforeSrc: url ? appAssetSrc(url) : null,
    candidate: candidate
      ? { label: candidate.record.label || candidate.record.id, previewSrc: candidateUrl ? appAssetSrc(candidateUrl) : null }
      : null,
    canEdit,
    editing: ai.editing,
    generating: ai.generating,
    hasImage: url !== "",
    onAccept: () => runner.accept(target),
    onEdit: (instruction) => void runner.edit(target, instruction),
    onGenerate: (prompt) => void runner.generate(target, prompt),
    onRejectCandidate: () => runner.reject(),
    onRemoveBackground: () => void runner.edit(target, REMOVE_BACKGROUND_INSTRUCTION, true),
    onSaveCandidateAsNew: () => runner.saveAsNew(),
    savedNotice: notice,
    statusLine: null,
  };
}
```

- [ ] **Step 4: Run the logic tests.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/hooks/site-images.logic.test.ts`
Expected: 7 passing, 0 failing.

- [ ] **Step 5: Write the images hook.**

`apps/frontend/src/features/site-editor/hooks/use-site-images.ts`:
```ts
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  kitLibraryEntries,
  type AssetLibraryCategory,
} from "@/features/design-editor/adapter/scene-asset-library";
import type { SceneImageAiBinding } from "@/features/design-editor/adapter/scene-image-ai";
import { listImageAssets, uploadWebAsset } from "@/features/design-editor/data/assets";
import { DESIGN_API_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";
import type { SceneAssetLibraryBinding } from "@/features/design-editor/hooks/use-scene-asset-library";
import { editSceneAsset, generateSceneAsset } from "@/features/design-editor/hooks/use-scene-image-ai";
import {
  EMPTY_SITE_IMAGE_AI,
  SITE_IMAGE_NOT_SAVED,
  appAssetSrc,
  assetIdForUrl,
  assetStoreUrlOf,
  createSiteImageAiRunner,
  siteImageAiBinding,
  type SiteImageAiDeps,
  type SiteImageTarget,
} from "./site-images.logic";

const ASSET_GONE = "That image is no longer in the library.";

export interface SiteImageFieldBinding {
  ai: SceneImageAiBinding;
  onFileSelect: (file: File) => Promise<void>;
  onOpenLibrary: () => void;
  previewSrc: string;
}

export interface SiteImages {
  field: (target: SiteImageTarget, value: string) => SiteImageFieldBinding;
  library: SceneAssetLibraryBinding | null;
  openLibraryFor: (target: SiteImageTarget) => void;
  uploadToLibraryTarget: (file: File) => Promise<void>;
}

/** The site lane's asset library binding (the ad lane's panel, unchanged) and its upload and AI
 * paths. Every path ends in `place(target, url)` — the session's insert_asset + save. */
export function useSiteImages({
  clearMessages,
  currentUrl,
  documentId,
  imagesVisible,
  kit,
  onError,
  place,
  writable,
}: {
  clearMessages: () => void;
  currentUrl: (target: SiteImageTarget) => string;
  documentId: string | null;
  /** The dock is showing an image field: load the registry so Edit can find the source asset. */
  imagesVisible: boolean;
  kit: unknown;
  onError: (message: string) => void;
  place: (target: SiteImageTarget, url: string) => boolean;
  writable: () => boolean;
}): SiteImages {
  const [libraryTarget, setLibraryTarget] = useState<(SiteImageTarget & { documentId: string }) | null>(null);
  const [registry, setRegistry] = useState<AssetRecord[]>([]);
  const [registryLoaded, setRegistryLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<AssetLibraryCategory | "all">("all");
  const [ai, setAi] = useState(EMPTY_SITE_IMAGE_AI);

  const latest = useRef({ clearMessages, currentUrl, documentId, libraryTarget, onError, place, registry, writable });
  useEffect(() => {
    latest.current = { clearMessages, currentUrl, documentId, libraryTarget, onError, place, registry, writable };
  });

  const generation = useRef(0);
  const refresh = useCallback(() => {
    const run = ++generation.current;
    setLoading(true);
    setError(null);
    void listImageAssets()
      .then((records) => {
        if (run !== generation.current) return;
        setRegistry(records as unknown as AssetRecord[]);
        setRegistryLoaded(true);
      })
      .catch((cause: unknown) => {
        if (run === generation.current) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (run === generation.current) setLoading(false);
      });
  }, []);
  useEffect(() => {
    if (imagesVisible && documentId && !registryLoaded) refresh();
  }, [documentId, imagesVisible, refresh, registryLoaded]);

  const lastTarget = useRef<SiteImageTarget | null>(null);
  const openLibraryFor = useCallback(
    (target: SiteImageTarget) => {
      if (!documentId) return;
      lastTarget.current = target;
      setQuery("");
      setCategory("all");
      setLibraryTarget({ ...target, documentId });
      refresh();
    },
    [documentId, refresh],
  );
  const isOpen = libraryTarget !== null && libraryTarget.documentId === documentId;
  const kitEntries = useMemo(() => kitLibraryEntries(kit), [kit]);
  const inUseAssetId = isOpen && libraryTarget ? assetIdForUrl(registry, currentUrl(libraryTarget)) : null;
  const items = useMemo(
    () => filterAssetLibrary(composeAssetLibrary({ inUseAssetId, kitEntries, registry }), { category, query }),
    [category, inUseAssetId, kitEntries, query, registry],
  );

  const placeFile = useCallback(async (target: SiteImageTarget, file: File) => {
    const now = latest.current;
    if (!now.writable()) throw new Error("not writable");
    let url: string | null;
    try {
      url = assetStoreUrlOf(await uploadWebAsset(file));
    } catch (cause) {
      now.onError(cause instanceof Error ? cause.message : String(cause));
      throw cause;
    }
    if (!url) {
      now.onError(SITE_IMAGE_NOT_SAVED);
      throw new Error(SITE_IMAGE_NOT_SAVED);
    }
    if (!latest.current.place(target, url)) throw new Error("not placed");
  }, []);

  const pick = useCallback((assetId: string) => {
    const now = latest.current;
    const target = now.libraryTarget;
    if (!target || target.documentId !== now.documentId || !now.writable()) return;
    const record = now.registry.find((candidate) => candidate.id === assetId);
    if (!record) {
      now.onError(ASSET_GONE);
      return;
    }
    const url = assetStoreUrlOf(record);
    if (!url) {
      now.onError(SITE_IMAGE_NOT_SAVED);
      return;
    }
    if (now.place(target, url)) setLibraryTarget(null);
  }, []);

  const uploadToLibraryTarget = useCallback(
    async (file: File) => {
      const target = latest.current.libraryTarget;
      if (!target) return;
      await placeFile(target, file);
      refresh();
    },
    [placeFile, refresh],
  );

  const aiDeps = useRef<SiteImageAiDeps | null>(null);
  useEffect(() => {
    aiDeps.current = {
      clearMessages,
      currentUrl,
      documentId,
      edit: editSceneAsset,
      generate: generateSceneAsset,
      onError,
      place,
      publish: setAi,
      sourceAssetId: (url) => assetIdForUrl(latest.current.registry, url),
      writable,
    };
  });
  const runner = useMemo(
    () =>
      createSiteImageAiRunner(() => {
        if (!aiDeps.current) throw new Error("site image deps read before the first render committed");
        return aiDeps.current;
      }),
    [],
  );

  const field = useCallback(
    (target: SiteImageTarget, value: string): SiteImageFieldBinding => ({
      ai: siteImageAiBinding({ ai, canEdit: assetIdForUrl(registry, value) !== null, documentId, runner, target, url: value }),
      onFileSelect: (file) => placeFile(target, file),
      onOpenLibrary: () => openLibraryFor(target),
      previewSrc: appAssetSrc(value),
    }),
    [ai, documentId, openLibraryFor, placeFile, registry, runner],
  );

  const library: SceneAssetLibraryBinding | null = documentId
    ? {
        category,
        close: () => setLibraryTarget(null),
        error,
        isOpen,
        items,
        loading,
        open: () => {
          if (lastTarget.current) openLibraryFor(lastTarget.current);
        },
        pick,
        query,
        refresh,
        setCategory,
        setQuery,
        thumbnailUrl: (record) => `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(record.id)}/bytes`,
      }
    : null;

  return { field, library, openLibraryFor, uploadToLibraryTarget };
}
```

- [ ] **Step 6: Place images from the session, and open the library on `request_asset`.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
- extend the imports: `getAtPath` and `withAssetAt` from `@clue/site-kit/editor-site`; `import { useSiteImages, type SiteImageFieldBinding, type SiteImages } from "./use-site-images";`; `import type { SiteImageTarget } from "./site-images.logic";`;
- add to `SiteEditingSession`:
```ts
  imageField: (path: string, value: string) => SiteImageFieldBinding | null;
  images: SiteImages;
```
- add `const openLibraryRef = useRef<((target: SiteImageTarget) => void) | null>(null);` directly after `const [selection, setSelection] = useState<SiteSelection | null>(null);`;
- in `handleFrameMessage`'s switch, add before `default:`:
```ts
      case "request_asset":
        openLibraryRef.current?.({ componentId: message.payload.componentId, prop: message.payload.prop, target: message.payload.route });
        return;
```
- directly after the `selectLayer` callback (Task 9), add:
```ts
  // C6: every image path (library pick, upload, generate, accepted edit) ends here.
  const writableRef = useRef(() => false);
  useEffect(() => {
    writableRef.current = () => acceptsFrameEdits({ editing, locked });
  });
  const currentUrl = useCallback(
    (target: SiteImageTarget) => {
      const props = currentSite ? componentProps(currentSite.site, target.target, target.componentId) : null;
      const value = getAtPath(props, target.prop);
      return typeof value === "string" ? value : "";
    },
    [currentSite],
  );
  const insertAsset = useCallback(
    (target: SiteImageTarget, url: string): boolean => {
      if (!currentSite || !activeDocumentId || !acceptsFrameEdits({ editing, locked })) return false;
      const props = componentProps(currentSite.site, target.target, target.componentId);
      if (!props) return false;
      if (getAtPath(props, target.prop) === url) return true;
      const edited = withAssetAt(currentSite.site, target.target, target.componentId, target.prop, url);
      setAppSite({ ...currentSite, site: edited });
      post("insert_asset", { componentId: target.componentId, prop: target.prop, route: target.target, url }, activeDocumentId);
      save(edited, `inspector: set image ${target.prop}`);
      return true;
    },
    [activeDocumentId, currentSite, editing, locked, post, save],
  );
  const images = useSiteImages({
    clearMessages: saves.clearMessages,
    currentUrl,
    documentId: activeDocumentId,
    imagesVisible: Boolean(activeSelection?.fields.some((field) => field.kind === "image")),
    kit: load.brand?.kit ?? null,
    onError: saves.reportError,
    place: insertAsset,
    writable: () => writableRef.current(),
  });
  useEffect(() => {
    openLibraryRef.current = images.openLibraryFor;
  });
  const imageField = useCallback(
    (path: string, value: string): SiteImageFieldBinding | null =>
      activeSelection ? images.field({ componentId: activeSelection.componentId, prop: path, target: activeSelection.target }, value) : null,
    [activeSelection, images],
  );
```
- add `images,` and `imageField,` to the returned object.

- [ ] **Step 7: The image field in the dock, and the library over the stage.**

In `apps/frontend/src/features/chat-shell/components/image-inspector.tsx`, change `function AdImageAiRows({` to `export function AdImageAiRows({` (no other change).

`apps/frontend/src/features/chat-shell/components/site-image-field.tsx`:
```tsx
"use client";

import type { SiteImageFieldBinding } from "@/features/site-editor/hooks/use-site-images";
import { AdImageAiRows } from "./image-inspector";
import { InspectorField, InspectorImageUpload } from "./inspector-primitives";

/**
 * DESIGN REVIEW (DR7): a site image field — the designed "Replace image" pill with its Upload /
 * Library menu, then the ad inspector's designed generate rows, unchanged. Both are disabled while
 * the agent-run lock holds (G-H: every control here is an operation or a spend).
 */
export function SiteImageField({
  binding,
  disabled,
  label,
}: {
  binding: SiteImageFieldBinding;
  disabled: boolean;
  label: string;
}) {
  return (
    <>
      <InspectorField label={label}>
        <InspectorImageUpload
          disabled={disabled}
          onFileSelect={binding.onFileSelect}
          onOpenLibrary={binding.onOpenLibrary}
          src={binding.previewSrc}
        />
      </InspectorField>
      <AdImageAiRows disabled={disabled} imageAi={binding.ai} />
    </>
  );
}
```

In `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, add `import { SiteImageField } from "./site-image-field";` and give the site dock's `<SiteInspector …>` (Task 9) this extra prop:
```tsx
                renderImageField={(field, path, value) => {
                  const binding = siteSession.imageField(path, value);
                  return binding ? (
                    <SiteImageField binding={binding} disabled={siteLocked} key={path} label={field.label} />
                  ) : null;
                }}
```
and replace the stage's `overlay={ sceneSession.assetLibrary?.isOpen ? ( … ) : null }` with:
```tsx
        overlay={
          sceneSession.assetLibrary?.isOpen ? (
            <AssetLibraryPanel
              library={sceneSession.assetLibrary}
              onUploadFile={sceneSession.onReplaceImage}
            />
          ) : siteSession.images.library?.isOpen ? (
            <AssetLibraryPanel
              library={siteSession.images.library}
              onUploadFile={siteSession.images.uploadToLibraryTarget}
            />
          ) : null
        }
```
Make the same two changes in `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` (import `SiteImageField`, add the same `renderImageField` prop to its `<SiteInspector …>` with `disabled={siteLocked}`, and the same `overlay`).

- [ ] **Step 8: The canvas asks for the library on a double-click on an image.**

In `apps/frontend/packages/site-editor/src/client/editor-app.tsx`, inside the listeners effect, add after `const onFocusOut = …;`:
```tsx
    const onDoubleClick = (event: MouseEvent) => {
      const state = controller.getState();
      if (state.mode !== "edit" || !state.site) return;
      const image = (event.target as Element | null)?.closest?.("img");
      const component = image?.closest("[data-puck-component]");
      const componentId = component?.getAttribute("data-puck-component");
      if (!image || !componentId) return;
      const props = state.site.pages[state.route]?.content.find((entry) => entry.props.id === componentId)?.props;
      const src = image.getAttribute("src") ?? "";
      // The field whose value IS this picture; a picture no field holds (a clone's own art) asks nothing.
      const prop = props ? Object.keys(props).find((key) => props[key] === src && src.startsWith("/asset-store/")) : undefined;
      if (prop) controller.requestAsset(state.route, componentId, prop);
    };
```
register it with `document.addEventListener("dblclick", onDoubleClick, true);` and remove it in the cleanup with `document.removeEventListener("dblclick", onDoubleClick, true);`.

- [ ] **Step 9: Run the suites, rebuild the editor, run the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -4 && npm test -w @clue/site-editor 2>&1 | tail -4 && npm run build -w @clue/site-editor && npm run design-system:build && npm run lint && npm run build`
Expected: both suites `# fail 0`; the editor builds; the gate's three commands exit 0.

- [ ] **Step 10: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/chat-shell/components apps/frontend/packages/site-editor/src/client/editor-app.tsx
git commit -m "site editor: image fields — the asset library, upload and the ad lane's generate rows place /asset-store urls via insert_asset; a canvas double-click asks for the library"
```

---

### Task 11: C7 — annotations for sites (selection reaches chat as annotation chips)

The web lane's annotation machinery is reused unchanged: the reducer (`design-editor/adapter/annotations.ts`), its session hook (`useWebAnnotations`), the comment box (`WebAnnotationPopover`, positioned from the iframe's rect plus the element geometry the frame reports), the chips above the composer and `annotationContextRefs`. The only new piece is the address: a site annotation's `WebElementAddress` carries the whole Lane A3 object id as its `nodeId` and no `path`, so `addressObjectId` returns exactly `site:<route>#<componentId>` (shell: `site:shell#header`) and `addressKey` stays unique. A click on a section or the shell in edit mode makes the frame post `annotate` (Task 6), which opens the box beside it.

The optional `.<propName>` suffix of the object id stays valid for A3 but is not produced in Wave 2: Puck renders its inline text fields with no DOM marker of the prop they edit, and Contract 6's `annotate` carries no prop.

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-annotations.ts` (+ `.test.ts`)
- Modify: `apps/frontend/src/features/site-editor/model/site-stage.ts` (`annotations`, `editing` on the canvas binding)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (annotations, `annotate`)
- Modify: `apps/frontend/src/features/design-editor/components/site-artifact-canvas.tsx` (the comment box)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (chips, refs, Send to chat)

**Interfaces:**
- Consumes: `useWebAnnotations`, `WebAnnotationsSession` (`design-editor/hooks/use-web-annotations.ts`), `PendingAnnotation` (`design-editor/adapter/annotations.ts`), `WebAnnotationPopover`, `addressKey`, `WebElementAddress` (`design-editor/engine/webBridge.ts`), `annotationChips`, `annotationContextRefs`, `ANNOTATIONS_ONLY_MESSAGE` (`chat-shell/model/edit-targets.ts`), Task 9's `componentLabel`, `cloneLabels`.
- Produces:
  - `model/site-annotations.ts`: `siteObjectId(target: string, componentId: string, prop?: string): string`, `siteAnnotationAddress(target: string, componentId: string, componentType: string): WebElementAddress`.
  - `SiteCanvasBinding.editing: boolean` and `SiteCanvasBinding.annotations: SiteCanvasAnnotations | null` with `interface SiteCanvasAnnotations { pending: PendingAnnotation | null; add(note?: string): void; dismiss(): void; editNote(note: string): void; onSend?: (note: string) => void }`.
  - `useSiteEditingSession` option `onSendAnnotation?: (note: string) => void`; `SiteEditingSession.annotations: WebAnnotationsSession`.

- [ ] **Step 1: Write the failing test.**

`apps/frontend/src/features/site-editor/model/site-annotations.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { WebAnnotation } from "@/features/design-editor/adapter/annotations";
import { addressKey, addressObjectId } from "@/features/design-editor/engine/webBridge";
import { annotationContextRefs } from "@/features/chat-shell/model/edit-targets";
import { siteAnnotationAddress, siteObjectId } from "./site-annotations";

test("the object id is exactly what Lane A3 validates", () => {
  assert.equal(siteObjectId("/analysis", "Hero-1a2b"), "site:/analysis#Hero-1a2b");
  assert.equal(siteObjectId("/analysis", "Hero-1a2b", "title"), "site:/analysis#Hero-1a2b.title");
  assert.equal(siteObjectId("/", "cta"), "site:/#cta");
  assert.equal(siteObjectId("shell", "header"), "site:shell#header");
});

test("a site address rides the web lane's annotation machinery unchanged", () => {
  const address = siteAnnotationAddress("/analysis", "Hero-1a2b", "FeatureSplit");
  assert.equal(addressObjectId(address), "site:/analysis#Hero-1a2b");
  assert.notEqual(addressKey(address), addressKey(siteAnnotationAddress("/", "Hero-1a2b", "FeatureSplit")));
});

test("a site turn carries one document ref and one noted design_node ref per annotation, in badge order", () => {
  const item = (n: number, target: string, componentId: string, note: string): WebAnnotation => ({
    address: siteAnnotationAddress(target, componentId, "StatsBand"),
    n,
    name: "Stats band",
    note,
    pageId: target === "shell" ? "/" : target,
    textLike: false,
  });
  assert.deepEqual(
    annotationContextRefs({
      documentId: "doc-site",
      documentVersion: 7,
      items: [item(2, "shell", "header", "Use the full district name"), item(1, "/", "proof", "Lead with 7.4%")],
    }),
    [
      { objectId: "doc-site", objectType: "design_document", version: 7 },
      { note: "1. Lead with 7.4%", objectId: "site:/#proof", objectType: "design_node", version: 7 },
      { note: "2. Use the full district name", objectId: "site:shell#header", objectType: "design_node", version: 7 },
    ],
  );
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-annotations.test.ts`
Expected: FAIL — `Cannot find module './site-annotations'`.

- [ ] **Step 3: Write the address model.**

`apps/frontend/src/features/site-editor/model/site-annotations.ts`:
```ts
import type { WebElementAddress } from "@/features/design-editor/engine/webBridge";

/** C7 / Lane A3: a site annotation's `design_node` object id — `site:<route>#<componentId>`, plus
 * an optional `.<propName>`; the shell's header and footer are `site:shell#header|footer`. */
export function siteObjectId(target: string, componentId: string, prop?: string): string {
  const base = `site:${target}#${componentId}`;
  return prop ? `${base}.${prop}` : base;
}

/** The web lane's reducer is address-agnostic: a site address carries its whole object id as the
 * `nodeId` and no `path`, so `addressObjectId` returns exactly the A3 id and `addressKey` stays
 * unique. `tag` is display-only. */
export function siteAnnotationAddress(target: string, componentId: string, componentType: string): WebElementAddress {
  return { nodeId: siteObjectId(target, componentId), tag: componentType };
}
```

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-annotations.test.ts`
Expected: 3 passing.

- [ ] **Step 4: Carry the comment box on the canvas binding.**

In `apps/frontend/src/features/site-editor/model/site-stage.ts`, add `import type { PendingAnnotation } from "@/features/design-editor/adapter/annotations";`, add the type below the imports:
```ts
/** The comment box's half of the web lane's annotation binding (badges are not drawn in a site). */
export interface SiteCanvasAnnotations {
  add: (note?: string) => void;
  dismiss: () => void;
  editNote: (note: string) => void;
  onSend?: (note: string) => void;
  pending: PendingAnnotation | null;
}
```
and add two members to `SiteCanvasBinding`:
```ts
  annotations: SiteCanvasAnnotations | null;
  /** Edit mode, unlocked: the comment box opens only then. */
  editing: boolean;
```

- [ ] **Step 5: Open, hold and expose annotations in the session.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
- add the imports:
```ts
import { pageFor } from "@clue/site-kit/editor-site";
import { useWebAnnotations, type WebAnnotationsSession } from "@/features/design-editor/hooks/use-web-annotations";
import { siteAnnotationAddress } from "../model/site-annotations";
import { componentLabel } from "../model/site-layers";
```
(merge `pageFor` into the existing `@clue/site-kit/editor-site` import and `componentLabel` into the existing `../model/site-layers` import);
- add `onSendAnnotation` to the options (`onSendAnnotation?: (note: string) => void;` in the type, and in the destructuring);
- add `annotations: WebAnnotationsSession;` to `SiteEditingSession`;
- directly after the `openLibraryRef` line (Task 10), add:
```ts
  const annotateRef = useRef<((payload: { componentId: string; geometry: PendingAnnotation["geometry"]; route: string }) => void) | null>(null);
```
(and `import type { PendingAnnotation } from "@/features/design-editor/adapter/annotations";`);
- in `handleFrameMessage`'s switch, add before `default:`:
```ts
      case "annotate":
        annotateRef.current?.(message.payload);
        return;
```
- directly after the `imageField` callback (Task 10), add:
```ts
  // C7: the web lane's annotations, one session per document, scoped by route.
  const annotations = useWebAnnotations(activeDocumentId, route);
  const openAnnotation = annotations.open;
  useEffect(() => {
    annotateRef.current = ({ componentId, geometry, route: target }) => {
      if (!acceptsFrameEdits({ editing, locked }) || !currentSite) return;
      const shellPart = target === "shell" ? componentId : null;
      const item = shellPart ? null : pageFor(currentSite.site, target)?.content.find((entry) => entry.props.id === componentId);
      const componentType = shellPart ? (shellPart === "header" ? "SiteHeader" : "SiteFooter") : (item?.type ?? "Section");
      const name = shellPart
        ? shellPart === "header" ? "Header" : "Footer"
        : componentLabel(componentType, item?.props ?? {}, cloneLabels);
      openAnnotation({ address: siteAnnotationAddress(target, componentId, componentType), geometry, name, textLike: false });
    };
  });
  const canvasAnnotations = useMemo(
    () => ({
      add: (note?: string) => {
        annotations.add(note);
      },
      dismiss: annotations.dismiss,
      editNote: annotations.editNote,
      onSend: onSendAnnotation,
      pending: annotations.state.pending,
    }),
    [annotations, onSendAnnotation],
  );
```
- in the returned `stage.canvas` object, add `annotations: canvasAnnotations,` and `editing: acceptsFrameEdits({ editing, locked }),`;
- add `annotations,` to the returned object.

- [ ] **Step 6: Draw the comment box over the site canvas.**

In `apps/frontend/src/features/design-editor/components/site-artifact-canvas.tsx`, add the imports:
```tsx
import { createPortal } from "react-dom";
import { addressKey } from "../engine/webBridge";
import { WebAnnotationPopover } from "./web-annotation-popover";
```
and add, as the last child of the returned fragment:
```tsx
      {/* C7: the web lane's comment box, positioned from the iframe's rect plus the geometry the
       * frame reported; portalled to <body> because `.artifactWorkspace` carries a transform. */}
      {binding.renderKind === "ready" && binding.editing && binding.annotations?.pending
        ? createPortal(
            <WebAnnotationPopover
              iframeRef={binding.iframeRef}
              key={addressKey(binding.annotations.pending.address)}
              onAdd={(note) => binding.annotations?.add(note)}
              onDismiss={binding.annotations.dismiss}
              onEditNote={binding.annotations.editNote}
              onSend={binding.annotations.onSend}
              pending={binding.annotations.pending}
            />,
            window.document.body,
          )
        : null}
```

- [ ] **Step 7: Chips, refs and "Send to chat" on the chats route.**

In `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`:
- directly after `const annotationLaneOpen = chat.designLegOpen && shell.artifactKind === "web";` add:
```tsx
  // C7: the site lane opens the same annotation lane beside an open design leg.
  const siteAnnotationLaneOpen = chat.designLegOpen && shell.artifactKind === "site";
```
- in the `useSiteEditingSession({ … })` call (Task 8), add `onSendAnnotation: siteAnnotationLaneOpen ? dispatchSendAnnotation : undefined,` — and move that call so it sits below the `dispatchSendAnnotation` declaration if it does not already;
- replace
```tsx
  const webAnnotationsEnabled =
    annotationLaneOpen && session.activeDocumentId !== null;
  const annotationChipList = webAnnotationsEnabled
    ? annotationChips(session.annotations.state.items)
    : [];
```
with
```tsx
  const webAnnotationsEnabled =
    annotationLaneOpen && session.activeDocumentId !== null;
  const siteAnnotationsEnabled =
    siteAnnotationLaneOpen && siteSession.activeDocumentId !== null;
  // One annotation lane at a time: the open artifact's.
  const activeAnnotations = webAnnotationsEnabled
    ? { annotations: session.annotations, documentId: session.activeDocumentId, version: session.webSelection.document?.currentVersion ?? null }
    : siteAnnotationsEnabled
      ? { annotations: siteSession.annotations, documentId: siteSession.activeDocumentId, version: siteSession.saves.baseVersion ?? siteSession.version }
      : null;
  const annotationChipList = activeAnnotations
    ? annotationChips(activeAnnotations.annotations.state.items)
    : [];
```
- in `submitTurn`, replace
```tsx
    const annotationItems = webAnnotationsEnabled
      ? [...session.annotations.state.items, ...(justAdded ? [justAdded] : [])]
      : [];
    const annotationSnapshot =
      webAnnotationsEnabled && session.activeDocumentId && annotationItems.length
        ? {
            documentId: session.activeDocumentId,
            documentVersion:
              session.webSelection.document?.currentVersion ?? null,
            items: annotationItems,
          }
        : null;
```
with
```tsx
    const annotationItems = activeAnnotations
      ? [...activeAnnotations.annotations.state.items, ...(justAdded ? [justAdded] : [])]
      : [];
    const annotationSnapshot =
      activeAnnotations?.documentId && annotationItems.length
        ? {
            documentId: activeAnnotations.documentId,
            documentVersion: activeAnnotations.version,
            items: annotationItems,
          }
        : null;
```
- replace `session.annotations.clear();` (after an accepted submit) with `session.annotations.clear();` followed by `siteSession.annotations.clear();`;
- in `sendAnnotation`, replace `const stored = session.annotations.add(note);` with `const stored = (activeAnnotations?.annotations ?? session.annotations).add(note);`;
- in the chips bar, replace `onClick={() => session.annotations.remove(chip.n)}` with `onClick={() => activeAnnotations?.annotations.remove(chip.n)}`.

- [ ] **Step 8: Run the suite and the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -4 && npm run design-system:build && npm run lint && npm run build`
Expected: `# fail 0`; all three gate commands exit 0.

- [ ] **Step 9: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/design-editor/components/site-artifact-canvas.tsx apps/frontend/src/features/chat-shell/components/chat-surface.tsx
git commit -m "site editor: annotations — site:<route>#<componentId> design_node refs on the web lane's reducer, comment box and chips"
```

---

### Task 12: C8 — edit toggle, live reload, the agent-run lock and undo/redo through the server stack

Most of C8's plumbing landed with Task 8 (the Edit pill drives `set_mode` through `siteFrameMode`; a `design.checkpoint` frame bumps `canvasRevision`, which calls `siteSession.reload()`, which sends `replace_site`; the lock refuses entry into edit mode and puts the frame in preview; the generating veil runs over a site). This task finishes it:

- **Undo / redo use the server stack (ruling), from three places:** the header menu's Undo/Redo (the existing `clue:artifact-action-request` window event, now honoured for `kind: "site"`), ⌘Z/⇧⌘Z pressed in the app outside an input, and ⌘Z/⇧⌘Z pressed inside the frame (the frame swallows Puck's own history and posts `shortcut`). All three go to `SiteSaveController.undo/redo`, which queues behind a pending save. Clicking the menu blurs the frame, and the frame's `focusout` listener sends any pending edit first.
- **The header's Undo/Redo disables** come from the server stack depths, and both are disabled while the lock holds.
- **The lock's sentence** shows in the dock's note line while the lock holds (the same words as on the Edit pill), so a dock that went inert mid-edit says why.

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-history.ts` (+ `.test.ts`)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (`shortcut`, listeners, `history`, lock note)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, `editor-surface.tsx` (header disables)

**Interfaces:**
- Consumes: Task 3 (`SiteSaves.undo/redo/undoDepth/redoDepth`), Task 4 (`shortcutFor`), `AGENT_RUN_LOCK_NOTE`.
- Produces:
  - `model/site-history.ts`: `siteHistoryActionFromEvent(detail: unknown): "undo" | "redo" | null` (only `{kind: "site", action: "undo" | "redo"}`), `siteHistoryDisabled(input: { depth: number; locked: boolean }): boolean`.
  - `SiteEditingSession.history: { redoDisabled: boolean; undoDisabled: boolean }`.

- [ ] **Step 1: Write the failing test.**

`apps/frontend/src/features/site-editor/model/site-history.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { siteHistoryActionFromEvent, siteHistoryDisabled } from "./site-history";

test("the header menu's undo and redo reach the site lane only for a site", () => {
  assert.equal(siteHistoryActionFromEvent({ action: "undo", kind: "site" }), "undo");
  assert.equal(siteHistoryActionFromEvent({ action: "redo", kind: "site" }), "redo");
  assert.equal(siteHistoryActionFromEvent({ action: "undo", kind: "web" }), null);
  assert.equal(siteHistoryActionFromEvent({ action: "archive", kind: "site" }), null);
  assert.equal(siteHistoryActionFromEvent(null), null);
});

test("undo and redo are offered only with a step to take and no agent at work", () => {
  assert.equal(siteHistoryDisabled({ depth: 0, locked: false }), true);
  assert.equal(siteHistoryDisabled({ depth: 3, locked: false }), false);
  assert.equal(siteHistoryDisabled({ depth: 3, locked: true }), true);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-history.test.ts`
Expected: FAIL — `Cannot find module './site-history'`.

- [ ] **Step 3: Write the model.**

`apps/frontend/src/features/site-editor/model/site-history.ts`:
```ts
/** The header menu's Undo/Redo arrive as the `clue:artifact-action-request` window event
 * (`use-artifact-action-menu-controller.ts`); the site lane answers only its own kind. */
export function siteHistoryActionFromEvent(detail: unknown): "undo" | "redo" | null {
  const value = detail as { action?: unknown; kind?: unknown } | null;
  if (!value || value.kind !== "site") return null;
  return value.action === "undo" || value.action === "redo" ? value.action : null;
}

/** Ruling: undo is the server's stack. A step is offered when the stack has one and no design
 * agent is at work on the document (the agent-run lock). */
export function siteHistoryDisabled({ depth, locked }: { depth: number; locked: boolean }): boolean {
  return locked || depth === 0;
}
```

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-history.test.ts`
Expected: 2 passing.

- [ ] **Step 4: Route every undo/redo to the server stack from the session.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
- extend the imports: `shortcutFor` from `@clue/site-kit/editor-site`; `import { siteHistoryActionFromEvent, siteHistoryDisabled } from "../model/site-history";`;
- add to `SiteEditingSession`: `history: { redoDisabled: boolean; undoDisabled: boolean };`;
- directly after the `annotateRef` line (Task 11), add:
```ts
  const stepRef = useRef<(action: "undo" | "redo") => void>(() => undefined);
```
- in `handleFrameMessage`'s switch, add before `default:`:
```ts
      case "shortcut":
        stepRef.current(message.payload.action);
        return;
```
- directly after the `canvasAnnotations` memo (Task 11), add:
```ts
  // C8: one history path — the server's stack — from the menu, the app's keyboard and the frame's.
  const undo = saves.undo;
  const redo = saves.redo;
  useEffect(() => {
    stepRef.current = (action) => {
      if (!activeDocumentId || locked) return;
      if (action === "undo") undo();
      else redo();
    };
  });
  useEffect(() => {
    if (!activeDocumentId) return;
    const onAction = (event: Event) => {
      const action = siteHistoryActionFromEvent((event as CustomEvent).detail);
      if (action) stepRef.current(action);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const decision = shortcutFor(event);
      if (decision !== "undo" && decision !== "redo") return;
      event.preventDefault();
      stepRef.current(decision);
    };
    window.addEventListener("clue:artifact-action-request", onAction);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("clue:artifact-action-request", onAction);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [activeDocumentId]);
  const history = {
    redoDisabled: siteHistoryDisabled({ depth: saves.redoDepth, locked }),
    undoDisabled: siteHistoryDisabled({ depth: saves.undoDepth, locked }),
  };
```
- in the `inspector` object (Task 9), replace `note: saves.note,` with:
```ts
    // The lock's own sentence while it holds (the Edit pill carries the same words).
    note: saves.note ?? (locked ? AGENT_RUN_LOCK_NOTE : null),
```
- add `history,` to the returned object.

- [ ] **Step 5: The header's Undo/Redo describe the site's stacks.**

In `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, replace
```tsx
        redoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : session.redoDisabled
        }
```
with
```tsx
        redoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : shell.artifactKind === "site"
              ? siteSession.history.redoDisabled
              : session.redoDisabled
        }
```
and replace
```tsx
        undoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : session.undoDisabled
        }
```
with
```tsx
        undoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : shell.artifactKind === "site"
              ? siteSession.history.undoDisabled
              : session.undoDisabled
        }
```
Make the same two replacements in `apps/frontend/src/features/chat-shell/components/editor-surface.tsx`, with `controller.artifactKind` in place of `shell.artifactKind`.

- [ ] **Step 6: Run the suite and the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -4 && npm run design-system:build && npm run lint && npm run build`
Expected: `# fail 0`; all three gate commands exit 0.

- [ ] **Step 7: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/chat-shell/components/editor-surface.tsx
git commit -m "site editor: undo/redo through the server stack from the menu, the app keyboard and the frame; header disables from the stacks; the lock's note in the dock"
```

---

### Task 13: C9 — versions from the server, restore through the server

The action menu's Versions submenu is a hard-coded list (`artifact-action-menu.tsx:93-98`) that dispatches a `clue:artifact-version-select` event nobody listens to (`use-artifact-action-menu-controller.ts:54-64`). For a site it now lists `GET /documents/{id}/site/versions` (newest first, the designed "Current version / Version N" labels) and a pick restores through `POST …/versions/{batch_id}/restore` — itself an undoable write (Contract 2), routed through the save controller so it queues behind a pending save and reloads the canvas. Web and ad keep the existing menu unchanged.

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-versions.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-versions.ts`
- Modify: `apps/frontend/src/features/chat-shell/model/artifact-actions.ts` (`ArtifactVersionsBinding`)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-action-menu.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-header.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`
- Modify: `apps/frontend/src/features/site-editor/model/site-stage.ts` (`versions`)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`

**Interfaces:**
- Consumes: Task 3 (`SiteRepository.versions`, `SiteVersion`, `SiteSaves.restore`), Task 8 (`SiteStageBinding`).
- Produces:
  - `chat-shell/model/artifact-actions.ts`: `interface ArtifactVersionsBinding { loading: boolean; open(): void; options: readonly { id: string; label: string }[]; select(id: string): void; selectedId: string | null }`.
  - `model/site-versions.ts`: `siteVersionOptions(versions: readonly SiteVersion[]): { id: string; label: string }[]`.
  - `useSiteVersions(options: { documentId: string | null; repository: SiteRepository; restore(batchId: string): void; version: number | null }): ArtifactVersionsBinding`.
  - `SiteStageBinding.versions: ArtifactVersionsBinding | null`; `ArtifactActionMenu` / `ArtifactHeader` prop `versions?: ArtifactVersionsBinding | null`.

- [ ] **Step 1: Write the failing test.**

`apps/frontend/src/features/site-editor/model/site-versions.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { siteVersionOptions } from "./site-versions";

test("versions read newest first with the menu's designed labels", () => {
  assert.deepEqual(
    siteVersionOptions([
      { actorKind: "human", batchId: "batch_9", createdAt: "2026-10-11T10:09:00Z", intent: null, version: 9 },
      { actorKind: "agent", batchId: "batch_8", createdAt: "2026-10-11T10:08:00Z", intent: null, version: 8 },
      { actorKind: "agent", batchId: "batch_5", createdAt: "2026-10-11T10:05:00Z", intent: null, version: 5 },
    ]),
    [
      { id: "batch_9", label: "Current version" },
      { id: "batch_8", label: "Version 8" },
      { id: "batch_5", label: "Version 5" },
    ],
  );
  assert.deepEqual(siteVersionOptions([]), []);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-versions.test.ts`
Expected: FAIL — `Cannot find module './site-versions'`.

- [ ] **Step 3: Write the model and the hook.**

`apps/frontend/src/features/site-editor/model/site-versions.ts`:
```ts
import type { SiteVersion } from "./site-wire";

/** The action menu's designed rows (plan Q4 (a)): the newest is "Current version", the rest
 * "Version N". Who made a version and when is not shown until there is a design for it. */
export function siteVersionOptions(versions: readonly SiteVersion[]): { id: string; label: string }[] {
  return versions.map((version, index) => ({
    id: version.batchId,
    label: index === 0 ? "Current version" : `Version ${version.version}`,
  }));
}
```

In `apps/frontend/src/features/chat-shell/model/artifact-actions.ts`, append:
```ts
/** A real version list for the action menu's Versions submenu (sites, Wave 2 C9). Absent → the
 * menu keeps its existing list for the kinds that have no version read yet. */
export interface ArtifactVersionsBinding {
  loading: boolean;
  open: () => void;
  options: readonly { id: string; label: string }[];
  select: (id: string) => void;
  selectedId: string | null;
}
```

`apps/frontend/src/features/site-editor/hooks/use-site-versions.ts`:
```ts
"use client";

import { useCallback, useState } from "react";
import type { ArtifactVersionsBinding } from "@/features/chat-shell/model/artifact-actions";
import type { SiteRepository } from "../data/site.repository";
import { siteVersionOptions } from "../model/site-versions";
import type { SiteVersion } from "../model/site-wire";

const VERSION_LIMIT = 20;

/** The site's versions, read when the submenu opens; a list read for an older document version is
 * not shown (the next open reads it again). A failed read shows no rows (no new failure UI). */
export function useSiteVersions({
  documentId,
  repository,
  restore,
  version,
}: {
  documentId: string | null;
  repository: SiteRepository;
  restore: (batchId: string) => void;
  version: number | null;
}): ArtifactVersionsBinding {
  const [read, setRead] = useState<{ documentId: string; list: SiteVersion[]; version: number | null } | null>(null);
  const [loading, setLoading] = useState(false);
  const open = useCallback(() => {
    if (!documentId) return;
    setLoading(true);
    void repository
      .versions(documentId, VERSION_LIMIT)
      .then((list) => setRead({ documentId, list, version }))
      .catch(() => setRead({ documentId, list: [], version }))
      .finally(() => setLoading(false));
  }, [documentId, repository, version]);
  const list = read && read.documentId === documentId && read.version === version ? read.list : [];
  const options = siteVersionOptions(list);
  const selectedId = options[0]?.id ?? null;
  const select = useCallback(
    (id: string) => {
      if (id !== selectedId) restore(id);
    },
    [restore, selectedId],
  );
  return { loading, open, options, select, selectedId };
}
```

- [ ] **Step 4: The menu and the header take a real list when one exists.**

In `apps/frontend/src/features/chat-shell/components/artifact-action-menu.tsx`:
- change the import to `import type { ArtifactActionRequest, ArtifactVersionsBinding } from "../model/artifact-actions";`;
- add `versions = null,` to the destructured props and `versions?: ArtifactVersionsBinding | null;` (with the doc comment `/** C9: a real version list (sites); absent keeps the existing list. */`) to the props type;
- replace the `const versionOptions = [ … ];` block with:
```tsx
  const versionOptions = versions
    ? versions.options
    : [
        { id: "current", label: "Current version" },
        { id: "version-3", label: "Version 3" },
        { id: "version-2", label: "Version 2" },
        { id: "version-1", label: "Version 1" },
      ];
  const shownVersionId = versions ? versions.selectedId : selectedVersionId;
  const openVersions = () => {
    if (versions && !versionsOpen) versions.open();
    onVersionsOpenChange(true);
  };
  const chooseVersion = (versionId: string) => (versions ? versions.select(versionId) : onSelectVersion(versionId));
```
- in the Versions row, replace the three `onVersionsOpenChange(true)` calls (on `onMouseEnter`, `onClick` and the ArrowRight `onKeyDown`) with `openVersions()`;
- in the version items, replace `selectedVersionId === version.id` (all three occurrences) with `shownVersionId === version.id`, and `onClick={() => onSelectVersion(version.id)}` with `onClick={() => chooseVersion(version.id)}`.

In `apps/frontend/src/features/chat-shell/components/artifact-header.tsx`:
- add `import type { ArtifactVersionsBinding } from "../model/artifact-actions";`;
- add `versions = null,` to the destructured props and, to the props type, `/** C9: the site's real version list. */ versions?: ArtifactVersionsBinding | null;`;
- add `versions={versions}` to `<ArtifactActionMenu …>`.

In `apps/frontend/src/features/site-editor/model/site-stage.ts`, add `import type { ArtifactVersionsBinding } from "@/features/chat-shell/model/artifact-actions";` and the member `versions: ArtifactVersionsBinding | null;` to `SiteStageBinding`.

In `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`, add `versions={artifactKind === "site" ? (site?.versions ?? null) : null}` to `<ArtifactHeader …>`.

- [ ] **Step 5: The session provides the list and the restore.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`, add `import { useSiteVersions } from "./use-site-versions";`, and directly after the `history` object (Task 12) add:
```ts
  // C9: versions from the server; a restore is an undoable write that queues behind a pending save.
  const versions = useSiteVersions({
    documentId: activeDocumentId,
    repository,
    restore: saves.restore,
    version: saves.baseVersion ?? currentSite?.version ?? null,
  });
```
and add `versions: activeDocumentId ? versions : null,` to the returned `stage` object.

- [ ] **Step 6: Run the suite and the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -4 && npm run design-system:build && npm run lint && npm run build`
Expected: `# fail 0`; all three gate commands exit 0.

- [ ] **Step 7: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/chat-shell
git commit -m "site editor: the Versions submenu reads the site's versions and restores through the server (replacing the hard-coded list and the dead event for sites)"
```

---

### Task 14: C10 — the pages UI from the founder's Ploy reference

Wave 2 ruling (founder, 2026-10-11): for a site, the stage's top bar gets a **Pages** toggle that opens a page panel on the left of the canvas — a count, a search box, one row per page with a home icon for `/`, each row titled by the page's title — and a browser-style **URL toolbar**: back, forward, the existing device menu, the current route (editable to jump), and reload. Adding, renaming and deleting pages stays with the agent. Everything is built from existing chat-shell styles and primitives; the new layout classes use only existing tokens and are marked DESIGN REVIEW (DR1–DR3).

Navigation always goes through the frame: the app sends `navigate`, the frame switches page and answers `navigated`, and that answer is what moves the active row, the route field and the back/forward history. Reload re-initialises the frame from a fresh read of the document.

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-pages.ts` (+ `.test.ts`)
- Create: `apps/frontend/src/features/chat-shell/components/site-pages-panel.tsx`
- Create: `apps/frontend/src/features/chat-shell/components/site-url-bar.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (DR2, DR3 classes)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-header.tsx` (Pages toggle, URL bar)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (panel state and placement)
- Modify: `apps/frontend/src/features/site-editor/model/site-stage.ts` (`pages`, `url`)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (history, navigate, reload)

**Interfaces:**
- Consumes: Task 8 (session, `post`, `reload`, `route`, `siteInitKey`), Task 4 (`pageFor`), `InspectorInput`, the `.layerRow*` classes, lucide `FilesIcon`, `HouseIcon`, `FileIcon`, `SearchIcon`, `ArrowLeftIcon`, `ArrowRightIcon`, `RotateCwIcon`.
- Produces:
  - `model/site-pages.ts`: `interface SitePageRow { active: boolean; home: boolean; route: string; title: string }`, `sitePageRows(site, activeRoute): SitePageRow[]`, `filterPageRows(rows, query): SitePageRow[]`, `interface RouteHistory { entries: string[]; index: number }`, `EMPTY_ROUTE_HISTORY`, `visitRoute(history, route): RouteHistory`, `stepRoute(history, step: -1 | 1): { history: RouteHistory; route: string | null }`, `parseRouteInput(text, site): string | null`, `interface SiteUrlBinding { back(): void; canBack: boolean; canForward: boolean; forward(): void; go(text: string): boolean; reload(): void; route: string }`.
  - `SiteStageBinding.pages: { open(route: string): void; rows: SitePageRow[] }`, `SiteStageBinding.url: SiteUrlBinding`.
  - `SitePagesPanel({ onOpen, rows })`, `SiteUrlBar({ binding, deviceMenu })`; `ArtifactHeader` prop `site?: { onTogglePages(): void; pagesOpen: boolean; url: SiteUrlBinding } | null`.

- [ ] **Step 1: Write the failing test.**

`apps/frontend/src/features/site-editor/model/site-pages.test.ts`:
```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import {
  EMPTY_ROUTE_HISTORY,
  filterPageRows,
  parseRouteInput,
  sitePageRows,
  stepRoute,
  visitRoute,
} from "./site-pages";

const site = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: {
    "/pricing": { root: { props: { title: "Pricing for SCSD" } }, content: [] },
    "/analysis": { root: { props: { title: "The free Provider Impact Analysis" } }, content: [] },
    "/": { root: { props: { title: "Garner Health for SCSD" } }, content: [] },
    "/faq": { root: { props: {} }, content: [] },
  },
  shell: null,
  agent_sections: {},
});

test("pages list home first, then the other routes in order, titled by their page title", () => {
  assert.deepEqual(
    sitePageRows(site, "/analysis").map((row) => [row.route, row.title, row.home, row.active]),
    [
      ["/", "Garner Health for SCSD", true, false],
      ["/analysis", "The free Provider Impact Analysis", false, true],
      ["/faq", "/faq", false, false],
      ["/pricing", "Pricing for SCSD", false, false],
    ],
  );
  assert.deepEqual(sitePageRows(null, "/"), []);
});

test("search matches a title or a route, ignoring case", () => {
  const rows = sitePageRows(site, "/");
  assert.deepEqual(filterPageRows(rows, "impact").map((row) => row.route), ["/analysis"]);
  assert.deepEqual(filterPageRows(rows, "FAQ").map((row) => row.route), ["/faq"]);
  assert.equal(filterPageRows(rows, "  ").length, 4);
});

test("back and forward walk the visited pages; a new visit drops the forward history", () => {
  let history = visitRoute(EMPTY_ROUTE_HISTORY, "/");
  history = visitRoute(history, "/analysis");
  history = visitRoute(history, "/analysis");
  assert.deepEqual(history, { entries: ["/", "/analysis"], index: 1 });
  const back = stepRoute(history, -1);
  assert.equal(back.route, "/");
  assert.equal(stepRoute(back.history, -1).route, null);
  assert.equal(visitRoute(back.history, "/").index, 0, "the frame's answer to a back step adds nothing");
  const branched = visitRoute(back.history, "/faq");
  assert.deepEqual(branched, { entries: ["/", "/faq"], index: 1 });
  assert.equal(stepRoute(branched, 1).route, null);
});

test("an address typed in the bar jumps only to a page the site has", () => {
  assert.equal(parseRouteInput("/analysis", site), "/analysis");
  assert.equal(parseRouteInput("analysis", site), "/analysis");
  assert.equal(parseRouteInput(" /Pricing/ ", site), "/pricing");
  assert.equal(parseRouteInput("", site), "/");
  assert.equal(parseRouteInput("/careers", site), null);
  assert.equal(parseRouteInput("https://garnerhealth.com", site), null);
});
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-pages.test.ts`
Expected: FAIL — `Cannot find module './site-pages'`.

- [ ] **Step 3: Write the model.**

`apps/frontend/src/features/site-editor/model/site-pages.ts`:
```ts
import { pageFor } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

/** One row of the page panel. Pages have no id or name of their own: the route is the identity
 * and the page title (`root.props.title`) is what the row says, falling back to the route. */
export interface SitePageRow {
  active: boolean;
  home: boolean;
  route: string;
  title: string;
}

export function sitePageRows(site: SiteDocument | null, activeRoute: string): SitePageRow[] {
  if (!site) return [];
  const routes = Object.keys(site.pages).sort((left, right) =>
    left === "/" ? -1 : right === "/" ? 1 : left < right ? -1 : left > right ? 1 : 0,
  );
  return routes.map((route) => {
    const title = pageFor(site, route)?.root.props.title?.trim();
    return { active: route === activeRoute, home: route === "/", route, title: title || route };
  });
}

export function filterPageRows(rows: readonly SitePageRow[], query: string): SitePageRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...rows];
  return rows.filter((row) => row.title.toLowerCase().includes(needle) || row.route.includes(needle));
}

/** The URL toolbar's back/forward: the pages the frame has shown, in order. */
export interface RouteHistory {
  entries: string[];
  index: number;
}

export const EMPTY_ROUTE_HISTORY: RouteHistory = { entries: [], index: -1 };

export function visitRoute(history: RouteHistory, route: string): RouteHistory {
  if (history.entries[history.index] === route) return history;
  const entries = [...history.entries.slice(0, history.index + 1), route];
  return { entries, index: entries.length - 1 };
}

export function stepRoute(history: RouteHistory, step: -1 | 1): { history: RouteHistory; route: string | null } {
  const index = history.index + step;
  if (index < 0 || index >= history.entries.length) return { history, route: null };
  return { history: { ...history, index }, route: history.entries[index] };
}

/** An address typed in the bar → a route the site has, or null (plan Q6 (a): the bar then shows
 * the current route again, saying nothing). */
export function parseRouteInput(text: string, site: SiteDocument | null): string | null {
  if (!site) return null;
  const trimmed = text.trim().toLowerCase();
  const withSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const route = withSlash.length > 1 ? withSlash.replace(/\/+$/, "") || "/" : "/";
  return pageFor(site, route) ? route : null;
}

/** What the URL toolbar needs. */
export interface SiteUrlBinding {
  back: () => void;
  canBack: boolean;
  canForward: boolean;
  forward: () => void;
  /** Jump to a typed address; false when the site has no such page. */
  go: (text: string) => boolean;
  reload: () => void;
  route: string;
}
```

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-pages.test.ts`
Expected: 4 passing.

- [ ] **Step 4: History, navigation and reload in the session.**

In `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`:
- add the import:
```ts
import {
  EMPTY_ROUTE_HISTORY,
  parseRouteInput,
  sitePageRows,
  stepRoute,
  visitRoute,
  type RouteHistory,
} from "../model/site-pages";
```
- directly after the `routeState` lines (Task 8), add:
```ts
  const [routeHistory, setRouteHistory] = useState<{ documentId: string; history: RouteHistory } | null>(null);
  const routeTrail = routeHistory && routeHistory.documentId === activeDocumentId ? routeHistory.history : EMPTY_ROUTE_HISTORY;
  const [initGeneration, setInitGeneration] = useState(0);
```
- in `handleFrameMessage`'s `case "navigated":`, add before its `return;`:
```ts
        setRouteHistory((previous) => ({
          documentId: message.documentId,
          history: visitRoute(previous && previous.documentId === message.documentId ? previous.history : EMPTY_ROUTE_HISTORY, message.payload.route),
        }));
```
- in the frame-sync effect (Task 8), replace `const initKey = siteInitKey(activeDocumentId, currentSite.site, boot);` with
```ts
    // The URL toolbar's reload bumps `initGeneration`, which forces a fresh init from a fresh read.
    const initKey = `${siteInitKey(activeDocumentId, currentSite.site, boot)}|${initGeneration}`;
```
and add `initGeneration` to that effect's dependency array;
- directly after the `versions` hook (Task 13), add:
```ts
  // C10: the page panel and the URL toolbar. Navigation always goes through the frame; its
  // `navigated` answer moves the active row, the route field and the history.
  const navigate = useCallback(
    (target: string) => {
      if (activeDocumentId) post("navigate", { route: target }, activeDocumentId);
    },
    [activeDocumentId, post],
  );
  const step = useCallback(
    (direction: -1 | 1) => {
      if (!activeDocumentId) return;
      const moved = stepRoute(routeTrail, direction);
      if (!moved.route) return;
      setRouteHistory({ documentId: activeDocumentId, history: moved.history });
      post("navigate", { route: moved.route }, activeDocumentId);
    },
    [activeDocumentId, routeTrail, post],
  );
  const pages = { open: navigate, rows: sitePageRows(currentSite?.site ?? null, route) };
  const url = {
    back: () => step(-1),
    canBack: routeTrail.index > 0,
    canForward: routeTrail.index >= 0 && routeTrail.index < routeTrail.entries.length - 1,
    forward: () => step(1),
    go: (text: string) => {
      const target = parseRouteInput(text, currentSite?.site ?? null);
      if (target) navigate(target);
      return target !== null;
    },
    reload: () => {
      setInitGeneration((generation) => generation + 1);
      reload();
    },
    route,
  };
```
- add `pages,` and `url,` to the returned `stage` object.

In `apps/frontend/src/features/site-editor/model/site-stage.ts`, add `import type { SitePageRow, SiteUrlBinding } from "./site-pages";` and the members `pages: { open: (route: string) => void; rows: SitePageRow[] };` and `url: SiteUrlBinding;` to `SiteStageBinding`.

- [ ] **Step 5: Write the page panel and the URL toolbar.**

In `apps/frontend/src/features/chat-shell/components/chat-shell.module.css`, add directly after the `.siteStage[hidden]` rule (Task 8):
```css
/* Lane C (sites): the canvas row — the page panel (when open) beside the canvas. */
.siteStageBody {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
}

/* DESIGN REVIEW (DR2): the page panel from the founder's Ploy reference. Built from the inspector
   rail's tokens; rows reuse `.layerRow*`, the search box `InspectorInput`. */
.sitePagesPanel {
  display: flex;
  flex: 0 0 280px;
  flex-direction: column;
  min-height: 0;
  border-right: 0.5px solid var(--chat-shell-border);
  background: var(--chat-shell-neutral);
}

.sitePagesPanelHead {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 16px 12px;
  border-bottom: 0.5px solid var(--chat-shell-border);
}

.sitePagesPanelList {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow: auto;
  padding: 8px;
}

/* DESIGN REVIEW (DR3): the browser-style URL toolbar. Buttons reuse `.deviceButton`; the field
   borrows `.artifactHeadingRenameInput`'s tokens. */
.siteUrlBar {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.siteUrlField {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  min-height: 34px;
  padding: 0 4px;
  border: 0.5px solid var(--chat-shell-border);
  border-radius: 4px;
  background: var(--chat-shell-page);
}

.siteUrlInput {
  width: 200px;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13px;
  line-height: 18px;
}
```

`apps/frontend/src/features/chat-shell/components/site-pages-panel.tsx`:
```tsx
"use client";

import { FileIcon, HouseIcon, SearchIcon } from "lucide-react";
import { useState } from "react";
import { filterPageRows, type SitePageRow } from "@/features/site-editor/model/site-pages";
import { InspectorInput } from "./inspector-primitives";
import styles from "./chat-shell.module.css";

/**
 * DESIGN REVIEW (DR2): the page panel (founder ruling 2026-10-11, the Ploy reference): a count, a
 * search box, one row per page with a home icon for "/". Adding, renaming and deleting pages stays
 * with the agent until those controls are designed.
 */
export function SitePagesPanel({ onOpen, rows }: { onOpen: (route: string) => void; rows: readonly SitePageRow[] }) {
  const [query, setQuery] = useState("");
  const shown = filterPageRows(rows, query);
  return (
    <nav aria-label="Pages" className={styles.sitePagesPanel}>
      <div className={styles.sitePagesPanelHead}>
        <span className={styles.inspectorFieldLabel}>{`Pages ${rows.length}`}</span>
        <InspectorInput
          ariaLabel="Search pages"
          leading={<SearchIcon absoluteStrokeWidth aria-hidden="true" size={14} strokeWidth={1.25} />}
          onChange={setQuery}
          placeholder="Search pages…"
          value={query}
        />
      </div>
      <div className={styles.sitePagesPanelList}>
        {shown.map((row) => {
          const Icon = row.home ? HouseIcon : FileIcon;
          return (
            <button
              aria-current={row.active ? "page" : undefined}
              className={`${styles.layerRow} ${row.active ? styles.layerRowActive : ""}`}
              key={row.route}
              onClick={() => onOpen(row.route)}
              title={row.route}
              type="button"
            >
              <span className={styles.layerRowContent}>
                <span className={styles.layerRowLabel}>
                  <Icon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
                  <span className={styles.layerRowLabelText}>{row.title}</span>
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
```

`apps/frontend/src/features/chat-shell/components/site-url-bar.tsx`:
```tsx
"use client";

import { ArrowLeftIcon, ArrowRightIcon, RotateCwIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { SiteUrlBinding } from "@/features/site-editor/model/site-pages";
import styles from "./chat-shell.module.css";

/**
 * DESIGN REVIEW (DR3): the browser-style URL toolbar (founder ruling 2026-10-11): back, forward, the
 * existing device menu, the current route — editable to jump — and reload. A route the site has no
 * page for puts the current route back and says nothing (plan Q6 (a); W3.3 bars new failure UI).
 */
export function SiteUrlBar({ binding, deviceMenu }: { binding: SiteUrlBinding; deviceMenu: ReactNode }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null) binding.go(draft);
    setDraft(null);
  };
  return (
    <div className={styles.siteUrlBar}>
      <button aria-label="Back" className={styles.deviceButton} disabled={!binding.canBack} onClick={binding.back} type="button">
        <ArrowLeftIcon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
      </button>
      <button aria-label="Forward" className={styles.deviceButton} disabled={!binding.canForward} onClick={binding.forward} type="button">
        <ArrowRightIcon absoluteStrokeWidth aria-hidden="true" size={16} strokeWidth={1.25} />
      </button>
      <div className={styles.siteUrlField}>
        {deviceMenu}
        <input
          aria-label="Page address"
          className={styles.siteUrlInput}
          onBlur={commit}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
            if (event.key === "Escape") setDraft(null);
          }}
          spellCheck={false}
          value={draft ?? binding.route}
        />
        <button aria-label="Reload page" className={styles.deviceButton} onClick={binding.reload} type="button">
          <RotateCwIcon absoluteStrokeWidth aria-hidden="true" size={14} strokeWidth={1.25} />
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: The header: the Pages toggle and the URL bar for a site.**

In `apps/frontend/src/features/chat-shell/components/artifact-header.tsx`:
- add `FilesIcon` to the `lucide-react` import, and the imports `import type { SiteUrlBinding } from "@/features/site-editor/model/site-pages";` and `import { SiteUrlBar } from "./site-url-bar";`;
- add `site = null,` to the destructured props and, to the props type:
```tsx
  /** C10 (sites): the Pages toggle's state and the URL toolbar. Absent on every other kind. */
  site?: { onTogglePages: () => void; pagesOpen: boolean; url: SiteUrlBinding } | null;
```
- move the device menu into a constant so the URL bar can hold it. Declare, directly before `return (`:
```tsx
  // The existing device menu, unchanged; for a site it sits inside the URL toolbar (C10).
  const deviceMenu = (
    <div className={styles.toolbarMenuAnchor} ref={deviceMenuRef}>
      <button
        aria-expanded={deviceMenuOpen}
        aria-haspopup="menu"
        aria-label={`Preview device: ${activeDevice}`}
        className={styles.deviceButton}
        onClick={() => {
          closeArtifactActionMenu();
          sharingController.closeMenu();
          toggleDeviceMenu();
        }}
        type="button"
      >
        <PreviewDeviceIcon
          absoluteStrokeWidth
          aria-hidden="true"
          size={16}
          strokeWidth={1.25}
        />
        <ChatShellIcon name="chevron-down" size={8} />
      </button>
      {deviceMenuOpen ? (
        <div aria-label="Preview device" className={styles.toolbarMenu} role="menu">
          {PREVIEW_DEVICES.map((option) => (
            <button
              aria-checked={activeDevice === option}
              className={`${styles.toolbarMenuItem} ${activeDevice === option ? styles.toolbarMenuItemActive : ""}`}
              key={option}
              onClick={() => chooseDevice(option)}
              role="menuitemradio"
              type="button"
            >
              <span>{option}</span>
              {activeDevice === option ? <CheckIcon aria-hidden="true" size={12} strokeWidth={1.5} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
```
  and replace the `: ( <div className={styles.toolbarMenuAnchor} ref={deviceMenuRef}> … </div> )` branch of `{kind === "ad" ? ( … ) : ( … )}` (today's `artifact-header.tsx:359-398`, the JSX now held by `deviceMenu`) with:
```tsx
        ) : site ? (
          <SiteUrlBar binding={site.url} deviceMenu={deviceMenu} />
        ) : (
          deviceMenu
        )}
```
- add, as the first child of `<div className={styles.artifactHeaderActions}>`:
```tsx
        {/* DESIGN REVIEW (DR1): the Pages toggle (founder ruling 2026-10-11, the Ploy reference) —
            the Edit pill's own button style and pressed state. */}
        {site ? (
          <button
            aria-pressed={site.pagesOpen}
            className={`${styles.artifactActionButton} ${site.pagesOpen ? styles.artifactActionButtonActive : ""}`}
            onClick={site.onTogglePages}
            type="button"
          >
            <FilesIcon absoluteStrokeWidth aria-hidden="true" size={14} strokeWidth={1.25} />
            <span>Pages</span>
          </button>
        ) : null}
```

- [ ] **Step 7: The stage owns the panel's open state and places it left of the canvas.**

In `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`:
- add `import { SitePagesPanel } from "./site-pages-panel";`;
- directly after the `previewDevice` state, add:
```tsx
  // C10: the page panel's open state is presentation, owned here like the device choice.
  const [pagesOpen, setPagesOpen] = useState(false);
```
- add to `<ArtifactHeader …>`:
```tsx
            site={
              artifactKind === "site" && site
                ? { onTogglePages: () => setPagesOpen((open) => !open), pagesOpen, url: site.url }
                : null
            }
```
- replace the persistent site stage block (Task 8) with this version — the canvas wrapper now sits in a row with the page panel first:
```tsx
      {site?.mounted ? (
        <div
          className={`${styles.outputStage} ${styles.webOutputStage} ${styles.siteStage}`}
          hidden={!siteFrameShown}
        >
          <div className={styles.siteStageBody}>
            {pagesOpen ? <SitePagesPanel onOpen={site.pages.open} rows={site.pages.rows} /> : null}
            <div aria-label="Web output canvas" className={webCanvasClass}>
              <SiteArtifactCanvas
                binding={site.canvas}
                onRenderKindChange={siteFrameShown ? setRenderKind : undefined}
              />
              <WebsiteGeneratingVeil active={siteFrameShown && veilActive} />
              <GeneratingGlow active={siteFrameShown && veilActive} />
            </div>
          </div>
        </div>
      ) : null}
```

- [ ] **Step 8: Run the suite and the gate.**

Run: `cd apps/frontend && npm test 2>&1 | tail -4 && npm run design-system:build && npm run lint && npm run build`
Expected: `# fail 0`; all three gate commands exit 0.

- [ ] **Step 9: Commit.**
```bash
git add apps/frontend/src/features/site-editor apps/frontend/src/features/chat-shell/components
git commit -m "site editor: the pages UI — a Pages toggle and page panel, and a browser-style URL toolbar (back, forward, device, route, reload) driven through the frame"
```

---

### Task 15: C11 — the editor domain in the dev stack and on Railway, and the containment test (Review focus 6)

The dev editor domain is `http://<label>.editor.localhost:<DEV_STACK_EDITOR_PORT>` (Contract 9): browsers resolve `*.localhost` to loopback with no DNS setup (the page-origin precedent, `DEV_STACK.md:129`), and a different host — not just a different port — keeps the app's host-only cookies away from the editor. `scripts/dev_stack.sh` starts the editor with the app origin, the design API and the suffix passed per process (the page-origin precedent: `.env` keeps the production default), and passes the same suffix to the dev frontend.

The containment test drives the **built** editor server on a `*.editor.localhost` host with the D2 spike's hostile and evasion probes compiled the way Lane B6 compiles a section and served through the real `/sections` route (a stub design API answers K1's verification route), embedded by a stub app page exactly as the app embeds it. It proves each probe ran (its headline is on screen) and that none escaped: no cookie of the app, no request to the app's API or to any other host, no top/parent navigation, and the policy reported each blocked attempt.

**Files:**
- Modify: `scripts/dev_stack.sh`, `scripts/dev_stack_trenton.sh`
- Modify: `.env.example` and the local `.env` (`DEV_STACK_EDITOR_PORT`)
- Create: `tests/test_site_editor_settings_documented.py`
- Create: `apps/frontend/packages/site-editor/Dockerfile.railway`
- Modify: `tests/deploy/test_frontend_image.py` (`DOCKERFILES`)
- Modify: `apps/frontend/docs/railway-deployment.md`, `DEV_STACK.md`
- Create: `apps/frontend/packages/site-editor/test/containment/compile-probes.ts`
- Create: `apps/frontend/packages/site-editor/test/containment/probes/ApiRead.tsx`
- Create: `tests/site_editor/test_editor_containment.py`

**Interfaces:**
- Consumes: Task 5 (server, env keys), Task 6 (build, the browser harness in `tests/site_editor/conftest.py`), the spike's probes `trials/puck-spike/scripts/hostile/{CookieRead,NetworkCall,ParentFrame,InjectedScript}.tsx` and `hostile/evasion/{ConstructorEscape,TopFrame,TrackingPixel}.tsx`.
- Produces: `DEV_STACK_EDITOR_PORT` (default `3120`; trenton `3129`); `./scripts/dev_stack.sh restart-editor`; the Railway service definition for the editor.

- [ ] **Step 1: Write the failing settings and dev-stack test.**

`tests/test_site_editor_settings_documented.py`:
```python
"""Lane C task C11: the site editor's settings ship their defaults and the dev stack runs it."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _value(path: str, key: str) -> str | None:
    match = re.search(rf"^{key}=(.*)$", (REPO / path).read_text(encoding="utf-8"), re.MULTILINE)
    return None if match is None else match.group(1).strip()


def test_the_editor_settings_are_documented_with_their_defaults() -> None:
    assert _value(".env.example", "CLUE_SITE_EDITOR_SUFFIX") == "edit.deeppresence.ai"
    assert _value(".env.example", "DEV_STACK_EDITOR_PORT") == "3120"
    assert _value("apps/frontend/.env.example", "CLUE_SITE_EDITOR_SUFFIX") == "edit.deeppresence.ai"
    package = "apps/frontend/packages/site-editor/.env.example"
    for key in ("PORT", "HOST", "CLUE_APP_ORIGIN", "LUMEN_API_BASE_URL", "CLUE_SITE_EDITOR_SUFFIX"):
        assert _value(package, key) is not None, f"{package} does not document {key}"


def test_the_dev_stack_runs_the_editor_on_its_own_domain() -> None:
    script = (REPO / "scripts/dev_stack.sh").read_text(encoding="utf-8")
    assert 'EDITOR_PORT="${DEV_STACK_EDITOR_PORT:-3120}"' in script
    assert "start_site_editor" in script and "stop_site_editor" in script
    assert 'CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}"' in script
    assert "restart-editor) restart_editor ;;" in script
    subprocess.run(["bash", "-n", str(REPO / "scripts/dev_stack.sh")], check=True)


def test_the_trenton_wrapper_requires_the_editor_port() -> None:
    assert "DEV_STACK_EDITOR_PORT" in (REPO / "scripts/dev_stack_trenton.sh").read_text(encoding="utf-8")
```

Run: `.venv/bin/python -m pytest tests/test_site_editor_settings_documented.py -q`
Expected: FAIL — `assert None == '3120'` (the port is not documented yet).

- [ ] **Step 2: Document the port.**

In `.env.example`, add directly after `DEV_STACK_PLATFORM2_PORT=8033`:
```bash
# Site editor (apps/frontend/packages/site-editor, Wave 2 Lane C), served at
# http://<label>.editor.localhost:<port>. scripts/dev_stack.sh passes CLUE_SITE_EDITOR_SUFFIX
# (editor.localhost:<port>) to it and to the frontend; .env keeps the production suffix.
DEV_STACK_EDITOR_PORT=3120
```
In the local `.env`, add `DEV_STACK_EDITOR_PORT=3129` directly after `DEV_STACK_PLATFORM2_PORT=8039` (the trenton lane: frontend 3029 → editor 3129).

- [ ] **Step 3: Start, stop and report the editor in the runbook script.**

In `scripts/dev_stack.sh`:
- change the first comment line to `# THE dev stack runbook. Commands: up|down|restart-api|restart-workers|restart-ingestion|restart-editor|status`;
- add to THE PORT MAP comment, after the `8040  page origin` entry:
```bash
#   3120  site editor (apps/frontend/packages/site-editor)
#                                — the Puck site editor on its own domain,
#                                  http://<label>.editor.localhost:3120, one
#                                  label per workspace. The app frames it; it
#                                  holds no login (Wave 2 D2 / Contract 9).
```
- add to the PORT KNOBS comment list: `#   DEV_STACK_EDITOR_PORT            site editor port             (default 3120)`;
- add directly after `PLATFORM2_PORT="${DEV_STACK_PLATFORM2_PORT:-8030}"`:
```bash
EDITOR_PORT="${DEV_STACK_EDITOR_PORT:-3120}"
```
- add directly after the `start_page_origin()` function:
```bash
# The site editor on its own domain (Wave 2 Contract 9): http://<label>.editor.localhost:$EDITOR_PORT.
# Its settings are passed per process, like the page origin's: .env keeps the production suffix.
# The command line names this checkout's absolute script path so pkill never touches a sibling lane.
start_site_editor() {
  ( cd "$ROOT/apps/frontend/packages/site-editor" && env \
      PORT="$EDITOR_PORT" HOST=127.0.0.1 \
      CLUE_APP_ORIGIN="http://localhost:${FRONTEND_PORT}" \
      LUMEN_API_BASE_URL="http://127.0.0.1:${DESIGN_PORT}" \
      CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}" \
      "$ROOT/apps/frontend/node_modules/.bin/tsx" "$ROOT/apps/frontend/packages/site-editor/scripts/dev.ts" \
      > "${LOG}_site_editor.log" 2>&1 & )
}

stop_site_editor() {
  pkill -f "$ROOT/apps/frontend/packages/site-editor/scripts/dev.ts" 2>/dev/null || true
}

# Restart ONLY the site editor (a change to its server code; client changes rebuild by themselves).
restart_editor() {
  load_env
  stop_site_editor
  for _ in $(seq 1 20); do
    lsof -iTCP:"$EDITOR_PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
  done
  start_site_editor
  echo "restarting site editor…"; sleep 6; status
}
```
- in `up()`, replace the frontend start line with
```bash
  ( cd "$ROOT/apps/frontend" && CLUE_SITE_EDITOR_SUFFIX="editor.localhost:${EDITOR_PORT}" \
      npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" \
      > "${LOG}_frontend.log" 2>&1 & )
  start_site_editor
```
  and add, after the `echo "app:   http://localhost:${FRONTEND_PORT}"` line:
```bash
  echo "editor: http://<label>.editor.localhost:${EDITOR_PORT} (one label per workspace; open a site in the app)"
```
- in `down()`, add `stop_site_editor` after the `pkill -f "next dev.*${FRONTEND_PORT}"` line;
- in `status()`, add `"$EDITOR_PORT site-editor"` to the `for spec in …` list (after `"8040 page-origin"`);
- in the final `case`, add `restart-editor) restart_editor ;;` after the `restart-ingestion)` line and add `restart-editor|` to the usage string.

In `scripts/dev_stack_trenton.sh`, add `#   3129  site editor     http://<label>.editor.localhost:3129` to the port comment, update the usage comment to `up|down|restart-api|restart-workers|restart-editor|status`, and add `DEV_STACK_EDITOR_PORT` to the `for key in …` list that `require`s keys from `.env`.

Run: `.venv/bin/python -m pytest tests/test_site_editor_settings_documented.py -q`
Expected: `3 passed`.

- [ ] **Step 4: The editor's Railway image, guarded like the frontend's.**

`apps/frontend/packages/site-editor/Dockerfile.railway`:
```dockerfile
# syntax=docker/dockerfile:1
# The Puck site editor (Wave 2 Lane C), served on the editor domain
# https://<label>.<CLUE_SITE_EDITOR_SUFFIX>. Build context: the repository root, like the frontend.

FROM node:22-bookworm-slim AS dependencies
WORKDIR /workspace/apps/frontend
# Every workspace manifest before `npm ci` (tests/deploy/test_frontend_image.py enforces it).
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/design-system/package.json ./packages/design-system/package.json
COPY apps/frontend/packages/site-kit/package.json ./packages/site-kit/package.json
COPY apps/frontend/packages/site-editor/package.json ./packages/site-editor/package.json
RUN npm ci

FROM node:22-bookworm-slim AS builder
WORKDIR /workspace/apps/frontend
COPY --from=dependencies /workspace/apps/frontend/node_modules ./node_modules
COPY --from=dependencies /workspace/apps/frontend/packages ./packages
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/site-kit ./packages/site-kit
COPY apps/frontend/packages/site-editor ./packages/site-editor
RUN npm run build -w @clue/site-editor

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000
WORKDIR /srv/site-editor
# The build is self-contained: the page, the bundle, the shims and the bundled server.
COPY --from=builder /workspace/apps/frontend/packages/site-editor/dist ./dist
USER node
EXPOSE 3000
CMD ["node", "dist/server.mjs"]
```

In `tests/deploy/test_frontend_image.py`, set:
```python
DOCKERFILES = ["apps/frontend/Dockerfile.railway", "apps/frontend/packages/site-editor/Dockerfile.railway"]
```
Run: `.venv/bin/python -m pytest tests/deploy/test_frontend_image.py -q` — Expected: `2 passed`.
Run: `docker build -f apps/frontend/packages/site-editor/Dockerfile.railway -t clue-site-editor-check . && docker run --rm -d --name clue-site-editor-check -p 3198:3000 -e CLUE_APP_ORIGIN=http://localhost:3029 -e LUMEN_API_BASE_URL=http://127.0.0.1:8019 -e CLUE_SITE_EDITOR_SUFFIX=editor.localhost:3198 clue-site-editor-check && sleep 2 && curl -s http://127.0.0.1:3198/healthz; docker rm -f clue-site-editor-check; docker image rm clue-site-editor-check`
Expected: the build succeeds and the health check prints `ok`.

- [ ] **Step 5: The Railway service notes.**

Append to `apps/frontend/docs/railway-deployment.md`:
```markdown
## Site editor service (Wave 2 Lane C)

A second Railway service serves the Puck site editor on its own registrable domain (D2):
`https://<label>.<CLUE_SITE_EDITOR_SUFFIX>`, one subdomain per workspace, where `<label>` is the
first 32 hex characters of sha256("clue-site-editor-label:v1:" + workspace id). It holds no login,
no secret and no database access.

- Source: this repository; Root Directory unset (repository root); service variable
  `RAILWAY_DOCKERFILE_PATH=/apps/frontend/packages/site-editor/Dockerfile.railway`.
- Watch paths: `/apps/frontend/packages/site-kit/**`, `/apps/frontend/packages/site-editor/**`,
  `/apps/frontend/package-lock.json`.
- Health check: `GET /healthz` (answers on any host).
- Variables: `PORT` (Railway sets it); `HOST=0.0.0.0` (the image sets it); `CLUE_APP_ORIGIN` — the
  app's canonical origin, the only origin allowed to frame and message the editor; `LUMEN_API_BASE_URL`
  — the design API's private URL (the token-checked section route and the public asset store);
  `CLUE_SITE_EDITOR_SUFFIX=edit.deeppresence.ai` — the editor domain (founder's choice, 2026-10-12).
- Domain: the wildcard custom domain `*.edit.deeppresence.ai`, a wildcard DNS record
  (`*.edit.deeppresence.ai` CNAME to the service's Railway target) and a wildcard certificate.
  Nothing is configured per workspace. Nothing with a login may ever run on `deeppresence.ai` or any
  subdomain of it while the editor lives there: code in the editor frame can set cookies for the
  whole registrable domain.
- The app service sets the same `CLUE_SITE_EDITOR_SUFFIX`; with it empty, a site shows the canvas
  error "The website editor is not configured for this environment."
- Never give this service Clerk keys, a database URL or any workspace secret.
```

- [ ] **Step 6: The dev-stack documentation.**

In `DEV_STACK.md`:
- add to the TL;DR block: `./scripts/dev_stack.sh restart-editor   # restarts ONLY the site editor (its server code changed; its client rebuilds by itself)`;
- add a row to the knobs table: `| DEV_STACK_EDITOR_PORT | site editor port (added 2026-10-11) | 3120 |`;
- add a row to "The port map": `| 3120 | site editor (apps/frontend/packages/site-editor) | The Puck site editor on its own domain, http://<label>.editor.localhost:3120 (one label per workspace; *.localhost resolves to loopback). The app frames it; it holds no login. A different host — not just a different port — is what keeps the app's cookies away from it. |`;
- add after the page-origin paragraph ("The page-origin keys are the one exception …"):
```markdown
The site editor follows the same rule: `.env` keeps the production `CLUE_SITE_EDITOR_SUFFIX`
(`edit.deeppresence.ai`, the founder's choice), and `scripts/dev_stack.sh` passes
`CLUE_SITE_EDITOR_SUFFIX=editor.localhost:<DEV_STACK_EDITOR_PORT>` to the editor and to the frontend
per process. Its log is `<prefix>_site_editor.log`. Its browser tests are opt-in:
`cd apps/frontend && npm run build -w @clue/site-editor && cd ../.. && CLUE_SITE_EDITOR_BROWSER=1 .venv/bin/python -m pytest tests/site_editor -q`.
```

- [ ] **Step 7: Write the containment test.**

`apps/frontend/packages/site-editor/test/containment/probes/ApiRead.tsx`:
```tsx
// Containment probe (Lane C, Review focus 6): an agent section that reads the APP's API with the
// marketer's cookies attached. The editor's policy must stop it before it leaves the frame.
import { z } from "zod";

export const schema = z.object({ id: z.string(), headline: z.string(), probe: z.string() }).strict();

export function render(props: z.infer<typeof schema>) {
  void fetch(props.probe, { credentials: "include" });
  return (
    <section>
      <h2>{props.headline}</h2>
    </section>
  );
}
```

`apps/frontend/packages/site-editor/test/containment/compile-probes.ts`:
```ts
// Compiles the D2 spike's hostile and evasion probes (and ApiRead) the way Lane B6 compiles an agent
// section — esbuild ESM, automatic JSX, react / react/jsx-runtime / zod external — and NEVER imports
// the result (plan Global Constraints: Node only transforms agent code). Prints {name: {digest, file}}.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../../..");
const HOSTILE = path.join(REPO, "trials/puck-spike/scripts/hostile");
const PROBES: Record<string, string> = {
  ApiRead: path.join(REPO, "apps/frontend/packages/site-editor/test/containment/probes/ApiRead.tsx"),
  ConstructorEscape: path.join(HOSTILE, "evasion/ConstructorEscape.tsx"),
  CookieRead: path.join(HOSTILE, "CookieRead.tsx"),
  InjectedScript: path.join(HOSTILE, "InjectedScript.tsx"),
  NetworkCall: path.join(HOSTILE, "NetworkCall.tsx"),
  ParentFrame: path.join(HOSTILE, "ParentFrame.tsx"),
  TopFrame: path.join(HOSTILE, "evasion/TopFrame.tsx"),
  TrackingPixel: path.join(HOSTILE, "evasion/TrackingPixel.tsx"),
};

const out = process.argv[2];
if (!out) throw new Error("usage: tsx compile-probes.ts <output directory>");
await fs.mkdir(out, { recursive: true });
const compiled: Record<string, { digest: string; file: string }> = {};
for (const [name, entry] of Object.entries(PROBES)) {
  const result = await build({
    bundle: true,
    entryPoints: [entry],
    external: ["react", "react/jsx-runtime", "zod"],
    format: "esm",
    jsx: "automatic",
    logLevel: "error",
    platform: "browser",
    write: false,
  });
  const code = result.outputFiles[0].text;
  const digest = createHash("sha256").update(code).digest("hex");
  const file = path.join(out, `${digest}.mjs`);
  await fs.writeFile(file, code);
  compiled[name] = { digest, file };
}
process.stdout.write(JSON.stringify(compiled));
```

`tests/site_editor/test_editor_containment.py`:
```python
"""Review focus 6 (master plan): agent-written section code loaded in the editor is contained.

The D2 spike's probes — a tracking pixel, a fetch reached through the Function constructor, top and
parent navigation, a cookie read, a beacon, an injected inline handler, and a credentialed read of
the app's own API — are compiled like real agent sections, served through the editor's token-checked
/sections route, and rendered by the built editor on a *.editor.localhost host inside the app's
sandboxed frame. Each must RUN (its headline is on screen) and none may escape.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .conftest import BROWSER_OPT_IN, COOKIE_SECRET, FRONTEND, TOKEN, editor_frame, garner_init, received

pytestmark = BROWSER_OPT_IN


def compile_probes(out: Path) -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["npx", "tsx", "packages/site-editor/test/containment/compile-probes.ts", str(out)],
        capture_output=True,
        check=True,
        cwd=FRONTEND,
        text=True,
    )
    return json.loads(result.stdout)


def test_hostile_agent_sections_run_and_are_contained(
    app: Any, browser_page: Any, design_api: Any, editor_origin: str, tmp_path: Path
) -> None:
    page, context = browser_page
    probes = compile_probes(tmp_path)
    for probe in probes.values():
        design_api.modules[probe["digest"]] = Path(probe["file"]).read_bytes()
    secret_url = f"{app.origin}/api/secret"
    base = garner_init(mode="preview")
    content = [
        {"type": name, "props": {"id": f"probe-{name.lower()}", "surface": "page", "headline": f"probe {name}", "probe": secret_url}}
        for name in probes
    ]
    site = {
        **base["site"],
        "agent_sections": {name: probe["digest"] for name, probe in probes.items()},
        "pages": {"/": {"root": {"props": {"title": "Probes"}}, "content": content}},
    }
    schema = {"type": "object", "properties": {"headline": {"type": "string"}, "probe": {"type": "string"}}}
    sections = [{"name": name, "digest": probe["digest"], "token": TOKEN, "propsSchema": schema} for name, probe in probes.items()]
    app.init_payload = {**base, "sections": sections, "site": site}
    escaped: list[str] = []

    def record_escape(route: Any) -> None:
        escaped.append(route.request.url)
        route.abort()

    context.route(re.compile(r"collector\.example"), record_escape)
    page.goto(app.origin + "/")
    frame = editor_frame(page, editor_origin)

    # Every probe that does not crash itself rendered: the containment below is not vacuous.
    for name in ("ApiRead", "CookieRead", "InjectedScript", "NetworkCall", "TrackingPixel"):
        frame.get_by_text(f"probe {name}").first.wait_for(timeout=20000)
    page.wait_for_timeout(2000)
    assert all(f"/site-sections/{probe['digest']}.mjs?t={TOKEN}" in design_api.requests for probe in probes.values())

    # 1. The app's cookie is not readable in the editor (another host).
    assert COOKIE_SECRET not in frame.evaluate("document.cookie")
    assert COOKIE_SECRET not in (frame.locator("[data-session]").first.get_attribute("data-session") or "")
    # 2. No credentialed call reached the app's API (ApiRead; ConstructorEscape aims at it too).
    assert app.secret_hits == []
    # 3. Nothing reached any other host: pixel, beacon, injected onerror handler.
    assert escaped == []
    # 4. No top or parent navigation; the app ignored the probes' own messages.
    assert page.url == app.origin + "/"
    assert not any(message.get("type") == "puck:publish" for message in received(page))
    # 5. The policy reported what it blocked.
    violations = frame.evaluate("window.__csp")
    directives = {violation["directive"] for violation in violations}
    assert "img-src" in directives, violations
    assert "connect-src" in directives, violations
    assert any(v["directive"].startswith("script-src") and v["blocked"] == "eval" for v in violations), violations
    # The two probes that throw (Function refused, top navigation refused) took nothing else down.
    assert frame.locator("[data-agent-section-failed]").count() >= 1
```

- [ ] **Step 8: Run the containment test.**

Run: `cd apps/frontend && npm run build -w @clue/site-editor && cd ../.. && CLUE_SITE_EDITOR_BROWSER=1 .venv/bin/python -m pytest tests/site_editor -q`
Expected: `3 passed` (the two renders tests and the containment test). If an assertion about a violation fails, read the `violations` list it prints: a missing `img-src`/`connect-src`/`eval` entry means that probe never ran (check its headline) or the policy changed — never relax the policy to make the test pass.

- [ ] **Step 9: Check the dev editor domain end to end on the running stack.**

Run: `./scripts/dev_stack_trenton.sh up`, then:
```bash
curl -s -D - -o /dev/null -H 'Host: 66f31149cfd649190785c03b5386a943.editor.localhost:3129' http://127.0.0.1:3129/ | grep -i -E '^(HTTP|content-security-policy)'
```
Expected: `HTTP/1.1 200 OK` and `frame-ancestors http://localhost:3029` inside the policy. Then sign in to `http://localhost:3029` with the dev login (DEV_STACK.md) and, in the browser's devtools on the app tab, confirm `document.cookie` lists the session cookies while the same expression evaluated in the editor frame's context (once a site is open) returns an empty string — Clerk's dev cookies are host-only and must not reach `*.editor.localhost`. **Owed (needs Lane A/B's K1–K4 routes and a workspace in `CLUE_DESIGN_SITE_ENGINE_WORKSPACES`):** the live walk — open a site, select a section (dock fields appear), edit text in the canvas and in the dock (one save each; the gallery card's version moves), Undo from the menu and with ⌘Z inside the frame, restore a version, switch pages from the panel and the URL bar, annotate a section and send it to chat, and watch an agent turn reload the canvas under the generating veil with the dock disabled. Record the result in `_memory/`. Stop the stack: `./scripts/dev_stack_trenton.sh down`.

- [ ] **Step 10: Run the frontend check gate and commit.**

Run: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`
Expected: all three exit 0.
```bash
git add scripts/dev_stack.sh scripts/dev_stack_trenton.sh .env.example tests/test_site_editor_settings_documented.py tests/deploy/test_frontend_image.py apps/frontend/packages/site-editor apps/frontend/docs/railway-deployment.md DEV_STACK.md tests/site_editor
git commit -m "site editor: the editor domain in the dev stack and on Railway, and the containment test over the D2 spike's hostile probes"
```

---

### Task 16: C12 — R5 spike: Puck's richtext field with an inline menu skinned from the platform toolbar

A spike-level answer, not production code (Wave 2 keeps plain `contentEditable` text as the default and changes no schema). The question: can Puck 0.23's `richtext` field, with `renderInlineMenu`, give marketers inline formatting on the canvas that looks like the platform's own rich-text toolbar (`features/design-editor/components/web-rich-text-toolbar.tsx` / `.module.css`), under the editor's real constraints (`Puck.Preview` only, Puck's canvas iframe disabled)? And what would adopting it cost (the stored value changes from a plain string to rich-text HTML, which touches `site-kit/src/schemas.ts`, the validator, the catalog and Lane A's sanitizer)?

The spike lives with the other spikes in `trials/puck-spike/` as a new page; nothing existing there changes.

**Files:**
- Create: `trials/puck-spike/app/r5-richtext/page.tsx`
- Create: `trials/puck-spike/app/r5-richtext/client.tsx`
- Create: `trials/puck-spike/app/r5-richtext/r5-menu.module.css`
- Create: `trials/puck-spike/export/check_richtext_r5.py`
- Create: `trials/puck-spike/RICHTEXT-R5.md`

**Interfaces:**
- Consumes: `@puckeditor/core` 0.23.0 (`Puck`, `Puck.Preview`, `RichTextMenu` and its `.Group`, `.Bold`, `.Italic`, `.Underline`, `.Strikethrough`, `.BulletList`, `.OrderedList`; the `richtext` field's `renderInlineMenu`, `options`, `contentEditable`).
- Produces: `trials/puck-spike/RICHTEXT-R5.md` — the answers and a recommendation for Wave 3.

- [ ] **Step 1: Write the spike page.**

`trials/puck-spike/app/r5-richtext/page.tsx`:
```tsx
// R5 spike (Lane C, C12): Puck's richtext field with an inline menu skinned like the platform's
// rich-text toolbar. Throwaway — the answer is RICHTEXT-R5.md, not this page.
import "@puckeditor/core/puck.css";
import { RichTextSpike } from "./client";

export default function Page() {
  return <RichTextSpike />;
}
```

`trials/puck-spike/app/r5-richtext/client.tsx`:
```tsx
"use client";

import { useState, type ReactNode } from "react";
import { Puck, RichTextMenu, type Config, type Data } from "@puckeditor/core";
import styles from "./r5-menu.module.css";

const BODY = "<p>Lower medical spend in year one. No plan changes.</p>";

// The editor's real constraints: Puck.Preview only, Puck's own canvas iframe off.
const config = {
  components: {
    RichTextProbe: {
      defaultProps: { body: BODY },
      fields: {
        body: {
          contentEditable: true,
          options: { blockquote: false, codeBlock: false, horizontalRule: false },
          renderInlineMenu: () => (
            <div className={styles.row} data-r5-inline-menu="true">
              <RichTextMenu.Group>
                <RichTextMenu.Bold />
                <RichTextMenu.Italic />
                <RichTextMenu.Underline />
                <RichTextMenu.Strikethrough />
              </RichTextMenu.Group>
              <span aria-hidden="true" className={styles.divider} />
              <RichTextMenu.Group>
                <RichTextMenu.BulletList />
                <RichTextMenu.OrderedList />
              </RichTextMenu.Group>
            </div>
          ),
          type: "richtext",
        },
      },
      render: ({ body }: { body: ReactNode }) => <section style={{ fontSize: 24, padding: 48 }}>{body}</section>,
    },
  },
} as unknown as Config;

const INITIAL: Data = {
  content: [{ props: { body: BODY, id: "probe" }, type: "RichTextProbe" }],
  root: { props: {} },
};

export function RichTextSpike() {
  const [data, setData] = useState<Data>(INITIAL);
  return (
    <>
      <Puck config={config} data={INITIAL} iframe={{ enabled: false }} onChange={setData}>
        <Puck.Preview />
      </Puck>
      <pre data-r5-data="true" style={{ fontSize: 11, padding: 16 }}>
        {JSON.stringify(data.content[0]?.props ?? null)}
      </pre>
    </>
  );
}
```

`trials/puck-spike/app/r5-richtext/r5-menu.module.css`:
```css
/* R5 spike: the platform rich-text toolbar's skin (apps/frontend/src/features/design-editor/components/
   web-rich-text-toolbar.module.css: .row, .tool, .divider) with the design-system tokens resolved to their
   values (apps/frontend/packages/design-system/generated/tokens.css), because the spike app does not ship
   the tokens: border-neutral #D6D9E0, bg-neutral #FFFFFF, content-neutral #1C2028, bg-neutral-hover
   #00256E07, bg-neutral-pressed #001E4B11, border-subtle #E6E9ED. */
.row {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border: 0.5px solid #d6d9e0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgb(0 24 62 / 12%);
  color: #1c2028;
  font-size: 13px;
  line-height: 18px;
}

.row :global(button) {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #1c2028;
  cursor: pointer;
}

.row :global(button:hover:not(:disabled)) {
  background: #00256e07;
}

/* Puck 0.23 marks an active inline control only by its hashed module class
   (`_ActionBarAction--active_<hash>`; chunk-K2LNXU54.mjs, `Action`) — no aria-pressed. */
.row :global(button[class*="ActionBarAction--active"]) {
  background: #001e4b11;
}

.divider {
  width: 1px;
  height: 22px;
  margin: 0 3px;
  background: #e6e9ed;
}
```

- [ ] **Step 2: Write the probe.**

`trials/puck-spike/export/check_richtext_r5.py`:
```python
"""R5 spike probe: the skinned inline menu appears on the canvas, and Bold changes the stored value."""

import asyncio
import json

from playwright.async_api import async_playwright

BASE = "http://localhost:3047"


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(f"{BASE}/r5-richtext", wait_until="load", timeout=60000)
        await page.get_by_text("Lower medical spend").first.click()
        await page.keyboard.press("ControlOrMeta+a")
        menu = page.locator("[data-r5-inline-menu]")
        await menu.wait_for(timeout=10000)
        await menu.get_by_title("Bold").click()
        await page.wait_for_timeout(500)
        stored = json.loads(await page.locator("[data-r5-data]").inner_text())
        border = await menu.evaluate("(element) => getComputedStyle(element).borderTopColor")
        active = await menu.evaluate(
            "(element) => [...element.querySelectorAll('button')].map((b) => b.outerHTML.slice(0, 160))"
        )
        await page.screenshot(path="shots/r5-richtext.png")
        print(json.dumps({"menu_visible": await menu.is_visible(), "menu_border": border,
                          "buttons": active, "stored_body": stored.get("body")}, indent=2))
        await browser.close()


asyncio.run(main())
```

- [ ] **Step 3: Run the spike.**

Run (two shells): `cd trials/puck-spike && npm run dev` (port 3047), then from the repo root `.venv/bin/python trials/puck-spike/export/check_richtext_r5.py`.
Expected: JSON with `"menu_visible": true`, `"menu_border": "rgb(214, 217, 224)"` and a `stored_body` string containing `<strong>`. Stop the dev server afterwards. A different result is a finding, not a failure: record it.

- [ ] **Step 4: Write the results note.**

`trials/puck-spike/RICHTEXT-R5.md` — one table, every row answered from Step 3's output, the screenshot `shots/r5-richtext.png` and what you saw while clicking and typing:
```markdown
# R5 spike: Puck richtext with an inline menu in the platform's skin (Lane C, C12)

Run on <date>, Puck 0.23.0, `trials/puck-spike/app/r5-richtext/`, probe `export/check_richtext_r5.py`.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Does `renderInlineMenu` render on the canvas with `Puck.Preview` only and Puck's iframe disabled? | | probe `menu_visible`, screenshot |
| 2 | Can it take the platform toolbar's skin (row, 32px tools, divider, pressed state)? Does the hashed `ActionBarAction--active` class hold up as the only active marker? | | `menu_border`, `buttons` |
| 3 | What does the field store after Bold (HTML string? JSON?) and what does `render` receive? | | `stored_body` |
| 4 | Does typing and formatting still work with ⌘Z swallowed by the frame (the editor's shortcut rule)? | | manual |
| 5 | What would adopting it touch: site-kit `schemas.ts` (string → rich text), `validate.ts`, the catalog and the agent's skills, Lane A's sanitizer allow-list (`strong`, `em`, `u`, `s`, `ul`, `ol`, `li`, `p`), the published render? | | reading the code |

## Recommendation for Wave 3
<adopt / adopt with changes / do not adopt, and the one reason>
```

- [ ] **Step 5: Commit.**
```bash
git add trials/puck-spike/app/r5-richtext trials/puck-spike/export/check_richtext_r5.py trials/puck-spike/RICHTEXT-R5.md trials/puck-spike/shots/r5-richtext.png
git commit -m "Puck spike: R5 — richtext with an inline menu in the platform toolbar's skin (results in RICHTEXT-R5.md)"
```

---

### Task 17: C13 — insert, delete and duplicate (outline only; blocked on the founder's designs)

Not executable in Wave 2. Puck can insert, delete, duplicate and reorder sections, but the editor turns all four off (`permissions: { delete: false, drag: false, duplicate: false, insert: false }` in `editor-app.tsx`) because the chat shell has no designed control for any of them, and the founder's rule is that new controls need a design first. When the designs land, the work is:

- **Design inputs needed:** where each control lives — the Layers row (a trailing "…" menu; `InspectorLayerRow` already has a `trailing` slot), the dock header's existing "More inspector actions" button (`InspectorHeader`'s `onMoreActions`), or a canvas toolbar; what "insert" offers (the brand sections, the seller's sections by their own labels, agent sections — never the words "clone" or "component"); whether reorder is drag on the canvas, drag in Layers, or up/down actions.
- **Protocol (a Contract 6 change, so the master plan first):** app → frame `insert_section {route, index, type, props}`, `remove_section {route, componentId}`, `duplicate_section {route, componentId}`, `move_section {route, componentId, index}`; the frame applies each with Puck's own actions (`insert`, `remove`, `duplicate`, `move` dispatches) and answers with `changed`. Or, if the controls live in the canvas, turn the matching Puck permission on and let `changed` carry the result.
- **Ids:** a new or duplicated section gets a fresh id matching `^[A-Za-z0-9_-]{1,200}$` (K5), unique on its page.
- **Saving:** unchanged — the app adopts `changed`, saves the whole site, one undo step per action.
- **Validation:** Lane A2's validator decides; a refused insert is a 422 like any other save.
- **Tests:** site-kit `editor-site.ts` grows `withInsertedSection`, `withoutSection`, `withDuplicatedSection`, `withMovedSection` (pure, tested); the frame controller tests each message; the browser harness inserts and removes a section and checks the saved site.

---

### Task 18: close-out — the session record

**Files:**
- Create: `_memory/2026-10-<day>-lane-c-site-editor.md` (the day you finish)

- [ ] **Step 1: Write the session note.** Per `CLAUDE.md`'s session memory protocol, record: the branch and the last commit; what each task delivered; the browser tests' results (`CLUE_SITE_EDITOR_BROWSER=1 .venv/bin/python -m pytest tests/site_editor -q`); the open questions Q1–Q6 and which were answered; the contract gaps K1–K7 and which lanes picked them up; the design review points DR1–DR7; and what is owed (the live walk in Task 15 Step 9, the R5 recommendation's follow-up, C13). No secrets, no customer data.

- [ ] **Step 2: Commit.**
```bash
git add _memory/2026-10-*-lane-c-site-editor.md
git commit -m "memory: Lane C site editor — delivered, tested, owed"
```

---

## Self-review notes

- **Spec coverage.** Contract 6 → Task 4 (schemas, acceptors), Task 6 (frame side), Task 8 (app side); refinements K6 recorded in the master plan in Task 4 Step 7. Contract 8 (frontend half, before Lane A's mapper) → Task 2. Contract 9 (editor domain half) → Tasks 4 (label/origin), 5 (host check), 7 (origin for the browser), 15 (dev domain, Railway). Contract 2 consumed → Tasks 3, 12, 13; Contract 4 consumed → Tasks 5 (route), 6 (loader), 8 (links, freshness); Contract 7 consumed → Task 8 (checkpoint reload); Contract 1 → Task 3. D2 frame attributes and CSP → Tasks 5, 8; Review focus 6 → Task 15. Rulings: fields in the app → Task 9; selection as annotation chips → Task 11; lock applies to sites → Tasks 8, 12; Puck history not the undo source → Tasks 6 (swallowed), 12; the app is the only saver → Tasks 3, 8; opaque label → Task 4; own-origin asset store → Tasks 5, 10; pages UI → Task 14; Railway build fix first → Task 1. C0–C13 each have a task (C3 split into Tasks 4–6, C4 into Tasks 7–8).
- **Placeholder scan.** Code steps carry full code; edits to large existing files name the exact text to replace. The only fill-ins are measured results (Task 16's note, Task 18's record), which are outputs by nature.
- **Type consistency.** Names used across tasks: `SiteDocument`, `SitePage`, `SiteTarget`, `SHELL_TARGET`, `SectionLink` (Task 3); `appToFrame`, `frameToApp`, `acceptAppMessage`, `acceptFrameMessage`, `FieldDescription`, `EditorMode`, `SiteGeometry` (Task 4); `componentProps`, `withComponentProps`, `withAssetAt`, `withPage`, `pageFor`, `getAtPath`, `setAtPath`, `canonicalJson`, `internalRoute`, `sectionDigests`, `shortcutFor` (Task 4); `editorLabelFor`, `editorOriginFor`, `editorLabelFromHost` (Task 4); `SiteRepository`, `SiteRepositoryError`, `LoadedSite`, `SiteVersion`, `SiteSaves`, `useSiteSaves` (Task 3); `SiteStageBinding`, `SiteCanvasBinding`, `useSiteEditingSession`, `SiteEditingSession` (Task 8, extended in 9–14 with `inspector`, `selection`, `images`, `imageField`, `annotations`, `history`, `stage.versions`, `stage.pages`, `stage.url`); `SiteInspectorBinding`, `SiteLayerRow` (Task 9); `SiteImageTarget`, `SiteImageFieldBinding`, `SiteImages` (Task 10); `ArtifactVersionsBinding` (Task 13); `SitePageRow`, `SiteUrlBinding` (Task 14).
- **Review Focus.** Each of the five lines has its test: 1 → Task 4 (`editor-protocol.test.ts`, the two acceptance tests); 2 → Task 8 (`site-frame-sync.test.ts`, "another document … each need a fresh init"); 3 → Task 3 (`site-save-controller.test.ts`, base-version refusal) and Task 8 (`frameSyncFor` replace on a new version); 4 → Task 8 (`linksFresh`); 5 → Task 8 (`acceptsFrameEdits`, `siteFrameMode`) and Task 12 (`siteHistoryDisabled`).
