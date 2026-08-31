# Brand-Kit × Onboarding Integration — Ratified Plan (parallel worktree)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans, task-by-task. **Process rule (founder, 2026-08-18, binding):
> Opus agents implement; the orchestrating session reviews every diff INLINE itself — never
> via a reviewer subagent.** Read this doc fully before any code. It is self-contained:
> every schema fact, file path, and ruling below was verified against the working tree on
> 2026-08-18 — trust it, but re-verify any file:line before editing (branches move).

**Worktree:** new Conductor workspace on branch `feature/brandkit-onboarding-integration`,
cut from `integration/frontend-design-part-iv-v2` (at or after commit `b9189131`). Merge
back locally into that branch when done — **never push; the founder pushes.** No AI
attribution anywhere. Commit per task.

**Goal:** the design subsystem's shipped brand-kit ingestion pipeline becomes part of
client onboarding: a first-time client's website is auto-ingested into a draft brand kit;
the co-founder's Brand-context page (dummy design, lifted verbatim) becomes the review +
approval surface; an approved kit automatically themes every NEW web document — which then
flows into the editor's color picker via the already-shipped theme feed (W4.0).

---

## 1. Founder rulings (2026-08-18) — do NOT re-litigate

1. **The 2026-08-12 "brand-kit stays out of onboarding" ruling is SUPERSEDED.** It existed
   only because the design subsystem was not yet merged into the monorepo; it now is
   (Part II done). Recorded supersession target: `docs/specs/FI-onboarding-contract-gap-review.md:140`
   (this worktree adds the dated supersession note there).
2. **Trigger semantics:** ingestion auto-fires **only during first-time onboarding**
   (the self-serve provisioning path). Every other case — additional workspaces, re-runs,
   refreshes — is **manual from the Brand-context screen**.
3. **The Brand-context page's dummy IS the parity baseline**: clue-frontend branch
   `codex/brand-context-page`, already merged to the dummy repo's `main`. **HARD
   CONSTRAINT: lift ONLY the brand-context files inventoried in §4 — nothing else.**
   Copy from the `main` checkout (`/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`);
   all 36 lift files are byte-identical between the branch and main (verified), and main
   wins for the shared files (which are re-authored, not copied — §4b).
4. **Approval consequence:** approving a kit makes it the automatic theme for all **NEW**
   web documents in the workspace. **Existing documents untouched** — therefore the
   mechanism is a stamp at document creation, NOT a render-time fallback change (a render
   fallback would silently re-theme existing ref-less documents; see §6 slice 5).
5. **Vision assist: ENABLED BY DEFAULT** in our deployments (`lumen_ingestion_vision` and
   `lumen_ingestion_describe` flip to on; OpenRouter-routed; model per existing config).
6. **OUT of scope:** the agent-facing L2 `BrandContextCard` digest (owned by
   `docs/specs/FI-production-deepagent-context-composition.md` §2.3's reader seam — leave
   the `MINIMAL` availability posture untouched).

## 2. Verified facts — the design subsystem (what you consume, never rebuild)

The ingestion pipeline is **fully shipped**. Scope your work as *connect and surface*.

- **Model (Rust, canonical):** `subsystems/clue-design/crates/lumen-core/src/brand.rs` —
  `BrandKit` (:193) `{id, version, name, sources, approval_status, modes, tokens: TokenCatalog,
  assets: BrandAssets{fonts,logos,images}, constraints: BrandConstraints{tone, contrast_pairs…}}`;
  `BrandApprovalStatus` draft→generated_unreviewed→approved→deprecated (:226);
  `platform_default_brand_kit()` (:251); `generate_brand_kit(seed)` (:2510).
- **Storage (platform Postgres):** `design_brand_kit` — migration
  `alembic/versions/51db518c2a68_design_brand_kits_part2_d1b.py`; PK `(brand_kit_id, version)`,
  **immutable version rows** (new version = new row), `workspace_id NOT NULL`,
  **`brand_id` born-nullable** composite FK `(brand_id, workspace_id) → brand`,
  `approval_status` + `product_ready` are the only mutable review columns,
  `brand_kit_json/brand_summary_json/diagnostics_json`. This IS "the platform versioned
  brand-kit payload" (ruling O2). Sibling: `design_ingestion_job` (kinds
  `website|pdf|asset_upload`, result pointer `(brand_kit_id, brand_kit_version)` —
  migration `e79f192828b1`).
- **Ingestion endpoints (design API, `subsystems/clue-design/apps/api/lumen_api/main.py`):**
  `POST /brand-kits/ingest/website` (:1502 — SSRF-guarded; job row + `design_job` fleet
  task in ONE txn; async worker executes), `/ingest/pdf` (:1527), `/ingest/assets` (:1593),
  `GET /brand-kits/ingest/{job_id}` (:1699 — status/progress), `GET /brand-kits` (:1489),
  `GET /brand-kits/{id}` (:1714), **`POST /brand-kits/{id}/approval` (:1754 — the human
  gate)**, `POST /documents/{id}/brand-kit` (:4731 — attach kit to a document).
- **Pipeline internals:** `apps/api/lumen_ingestion/` — `pipeline.py::run_website_ingestion`
  (:598); tier-1 static + tier-2 Playwright-rendered capture (`capture/rendered.py` — lazy
  import: **Playwright must be installed where the worker runs**); OKLCH 12-stop ramps
  (`normalizer/ramps.py::derive_ramp` :47); contrast-enforced role assignment
  (`normalizer/roles.py`); vision assist `capture/pdf_vision.py` (contract: vision may ADD,
  never mutate an extracted hex). **Vision + describe default OFF** at
  `packages/py-lumen-config/py_lumen_config/config.py:100-103` — ruling 5 flips our
  deployment defaults.
- **Theme derivation (the consequence chain):** `GET /documents/{id}/web/theme`
  (main.py:3470) → `resolve_web_turn_brand_kit` (main.py:8399) reads
  `web_doc["theme"]["brand_kit"]` `{id, version}`; **resolution failure NEVER fails the
  turn** — silent fallback to `platform_default_brand_kit()`. Token values compile in
  `crates/lumen-web/src/theme.rs::compile_web_theme` (:59): semantic web tokens
  (`primary/accent/dark/light/muted/border`) resolve through ordered kit-role chains
  (`SEMANTIC_TOKENS` :19-27); every other kit color is preserved under a sanitized name
  (`palette.primary.500` → `palette-primary-500`). **So: kit approved + referenced ⇒ the
  client's brand appears in the editor color picker (W4.0 feed) and the rendered page,
  with zero picker-side work.**
- **Kit birth ↔ brand join:** `subsystems/design/clue_design/` is the **platform-side DAL**
  (the composition root's port — distinct from the lumen_api service code):
  `joins.py::resolve_brand_id` (:82-113) — explicit id wins → exactly-one-brand wins →
  zero brands creates `"Default Brand"` → **≥2 brands returns None** (kit born unlinked).
  `brand.py::create_brand_kit` stamps via that heuristic. Consequence: the **auto path
  needs no new plumbing** (a first-time workspace has exactly one brand — the heuristic
  lands correctly); the **manual path must thread an explicit `brand_id`** (a workspace may
  be multi-brand by then).
- **What does NOT exist (your gaps to close or record):** no onboarding→ingestion wiring;
  no `brand_id` populated on kits (D3 join incomplete — your stamping closes it for the
  provisioning path; NOT NULL promotion stays deferred, don't attempt it); no auto-approval
  (never add one — taste is human-gated by design); no tone/voice LLM extraction from
  scraped copy (`BrandConstraints.tone` exists, nothing fills it from websites — recorded
  future work, OUT of scope here); no per-document theme table (nothing to migrate —
  only the kit ref matters).

## 3. Verified facts — the platform side (where you wire in)

- **`brand` spine row is name-only** (`libs/clue-spine/clue_spine/spine.py:62-70`, frozen,
  `extra="forbid"`). Born at self-serve provisioning:
  `platform/auth/clue_auth/provisioning.py:304` (`create_brand`, name = company name),
  recorded in `self_serve_provisioning(auth_identity_id, user_id, workspace_id, brand_id,
  company_website)` (:316-325), idempotent by advisory lock + replay (:363-407). **No brand
  HTTP API exists on the platform** — do not build one; this plan doesn't need it.
- **Stage-0 onboarding:** `platform/api/clue_api/stage0_setup.py` — `POST /stage0/setup`
  captures the provisioned company website (B2 capture-before-use) and fires client-KB
  recon; `GET /stage0/setup/current` resolves lane truth through `self_serve_provisioning`
  (:241) and returns per-field progress. Recon researches **11 `client.*` text fields,
  zero brand-visual fields** — brand ingestion is NOT recon's job; it runs beside it.
- **The dummy checklist row you make real:**
  `apps/frontend/src/features/onboarding/model/setup-items.ts:7-9` (`BRAND_KIT_ITEM_ID`)
  and `:212-215` — the "Creating brand kit — Colors, typography, tone & voice" row is
  force-downgraded to `queued` forever. The fixture copy lives at
  `features/onboarding/data/onboarding.fixture.ts:45,54-57`; the four real recon groups at
  `features/onboarding/data/setup-groups.ts:20-47`.
- **The dead nav item you bring alive:** `apps/frontend/src/config/navigation.ts:24`
  already has `{ href: "/brand-context", icon: "brand", label: "Brand context" }` — there
  is simply **no route behind it**. (The nav entry itself needs NO edit.)
- **The BFF design proxy** (`apps/frontend/src/app/api/clue/design/[...path]/…`) already
  fronts the design API with platform auth + server-side `X-Workspace-Id` stamping.
  **The design API must never be reachable from browsers directly** — every frontend call
  in this plan goes through `/api/clue/design/...`. Engine-side calls use
  `designBffConfig()` from `features/design-editor/data/design-bff.ts` (never hand-build a
  config — the engine's `new URL(path, apiBaseUrl)` contract requires it).
- **Theme feed precedent (W4.0, commit `cf228bc9`):** `useWebTheme` hook →
  `buildThemeColorOptions` mapper → context with fixture fallback. Mirror this idiom for
  any new read (hook in `features/design-editor/hooks/` or a feature-local `data/`
  repository; presentation components never import `data/` or the engine — the seam lint
  enforces it).

## 4. The Brand-context page lift (dummy = parity baseline)

Source checkout: `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`
(main). Inventory verified 2026-08-18; branch and main byte-identical on all 36 lift files.

### 4a. Lift VERBATIM (36 files — the complete list; nothing beyond it)

- Route: `src/app/brand-context/page.tsx` (Next 15+ semantics: awaits `searchParams`;
  target repo is compatible). **Re-home under our protected layout:**
  `apps/frontend/src/app/(protected)/brand-context/page.tsx`.
- Components (9): `src/features/brand-context/components/{brand-context-screen,
  brand-context-sidebar, brand-context-header, brand-context-icon, colors-panel,
  typography-panel, assets-panel, knowledge-panel, markdown-source-editor}.tsx`
- CSS module (1): `src/features/brand-context/components/brand-context.module.css`
  (1,816 lines, entirely `--clue-ds-*` token-driven).
- Hook (1): `src/features/brand-context/hooks/use-brand-context-controller.ts` (452 lines).
- Model (2): `src/features/brand-context/model/brand-context.ts` + `.test.ts`
  (node:test — our runner is `tsx --test`, same as the dummy's; NOT vitest).
- Data (2): `src/features/brand-context/data/brand-context.{fixture,repository}.ts`
  — `getBrandContextRepository()` flips fixture→HTTP on `CLUE_API_BASE_URL`; **this is the
  single backend wiring seam.**
- Public assets (19): `public/icons/brand-context/*.svg` (11) +
  `public/icons/brand-context/assets/*.svg` (8).
- Docs (2, into `apps/frontend/docs/`): `docs/api-contracts/brand-context.md` (the
  frontend-authored *proposal* — reconcile per §6 slice 2 and record resolutions back into
  it, per the repo's contract-gap convention) + `docs/figma/brand-context.md`.

**One cross-boundary import to adapt:** `brand-context-screen.tsx` imports
`@/components/shell/application-shell` (`ApplicationShell activeHref="/brand-context"`).
Our repo's shell is `ProjectApplicationShell` at the layout level (ruling R7 lineage) —
strip/adapt the wrapper the same way the Phase-C lifts did; the `(protected)` layout owns
the shell. Two global class names (`clue-view-enter`, `clue-scrollbar-hidden`) must exist
in our `globals.css` — verify, add if absent (they pre-date the branch in the dummy).

**Pre-existing icons the components reference (verify present in our repo; copy any
missing):** `public/icons/{filter,settings}.svg`, `public/icons/filters/trash.svg`,
`public/icons/detail/{x,breadcrumb-slash}.svg`,
`public/icons/projects/{check,sidebar-folder-open,sidebar-new-chat}.svg`. Fixture-only
images (`/logos/clue-sidebar.svg`, `/projects/home/abm-campaign.png`) already exist here.

### 4b. Re-author, do NOT copy (shared files — the dummy's copies have diverged)

- `package.json`: add `"codemirror": "^6.0.2"`, `"@codemirror/lang-markdown": "^6.5.2"`.
  `markdown-source-editor.tsx` also imports `@codemirror/{language,state,view}` and
  `@lezer/highlight` directly — declare them explicitly (transitive-only otherwise).
  `package-lock.json` regenerates via `npm install` — never copied.
- Design-system tokens: grep `brand-context.module.css` for `--clue-ds-color-button-` —
  if consumed, hand-add the 4 button tokens (`--clue-ds-color-button-{default,hover,
  pressed,disabled}` → brand-alpha `{700,800,900,200}`) to OUR token layer the way our
  design system does it. Do NOT copy the dummy's `generated/tokens.css` or its
  `build-tokens.mjs`/`source/production/**` changes (design-system infra, diverged).
- **EXCLUDE entirely:** `src/components/shell/app-sidebar.tsx` (1-line cosmetic border,
  main rewrote the file), `src/config/navigation.ts` (our entry already exists),
  `packages/design-system/**` (all), `docs/README.md`,
  `figma/components/pages/brand-context.json` (added by a different branch).

### 4c. The dummy's behavior contract (what "wired" means)

Data shape: `BrandContextWorkspaceSchema` — `colorGroups[{swatches[{lightValue,darkValue}]}]`,
`typefaces[]`, `textStyles[]`, `assets[{category, visual: image|gradient}]`,
`knowledgeFolders[{documents[{body: markdown}]}]`. Light/dark toggle is client-side (both
values ride every swatch). All interactions are today client-only in-memory (rename,
delete, uploads store filenames, etc.); **there are NO approve / ingest-trigger affordances
in the dummy** — see slice 4's founder gate. Sections and view state mirror into the URL
(`?section|view|theme|mode|file`) — deep-linkable; preserve exactly.

## 5. Contract decisions this plan pins (kit → page shape)

The dummy's `GET /api/v1/brand-context` proposal meets the real store as follows (v1):

- **Source of truth:** the workspace's **latest brand-kit version** (any approval status —
  the screen is precisely the review surface for drafts), read through the BFF
  (`GET /api/clue/design/brand-kits` list + detail). Multi-kit workspaces: newest
  `(brand_kit_id)` by latest version's `updated_at`; record the choice in the contract doc.
- **colorGroups** ← kit token catalog: semantic roles as one group; each ramp
  (`palette.primary.*`, `palette.neutral.*`) as its own group. `lightValue`/`darkValue`
  from the kit's modes (dark colorway per `normalizer/roles.py::build_dark_colorway`
  semantics; when the kit has no dark mode, `darkValue = lightValue` — honest, not
  fabricated).
- **typefaces / textStyles** ← `assets.fonts` (family, source) and the kit's type spec
  where present; **honest empties** where the kit carries none.
- **assets** ← `assets.logos` + `assets.images`; image bytes served through the BFF asset
  path (never a direct design-API URL); gradients only if the kit models one (else none).
- **knowledgeFolders** ← **honest empty in v1.** The kit's `constraints.tone` words are
  the only voice-shaped data and have no markdown-document form. Do NOT fabricate
  documents. Record "brand knowledge docs" in the contract doc's future-work section.
  (The dummy's knowledge fixtures render only in fixture mode.)
- **Mutations:** v1 wires **read + approval only**. The dummy's client-side edits (rename,
  delete, font upload, markdown editing) stay client-side-inert exactly as lifted — their
  persistence endpoints are future work (they're already proposed in the lifted contract
  doc; leave them proposed).

## 6. Slices

### Slice 0 — Page lift (fixture-backed)
Lift §4a verbatim; §4b re-authoring; route at `(protected)/brand-context`. The page renders
with the dummy's fixture data behind auth; sidebar nav item now resolves. Existing
model test green under `tsx --test`. Gate: `npm test && npm run lint && npm run
design-system:build && npm run build`. Browser-verify against the dummy's own reference
(`docs/figma/brand-context.md` fidelity checklist). Commit.

### Slice 1 — Read seam: kit → page
Platform-side read (the BFF is the transport; presentation untouched): implement the
§5 mapping as a pure, unit-tested mapper (kit JSON fixture harvested from a REAL ingested
kit — run one website ingestion against a dev workspace to harvest, do not hand-write the
fixture); extend the lifted repository's HTTP adapter to the real endpoint(s); flip the
page to live data with fixture fallback (the W4.0/W2.3 pattern). Honest empties per §5.
Tests: mapper per section; empty-kit → designed empty states; repository against mocked
BFF. Record every contract resolution in `apps/frontend/docs/api-contracts/brand-context.md`.
Commit per mapper group.

### Slice 2 — Auto-trigger at first-time onboarding
At the provisioning/Stage-0 boundary (recommended: alongside `POST /stage0/setup`'s
existing capture step, which already holds `brand_id` + `company_website` from
`self_serve_provisioning`), enqueue ONE website brand-kit ingestion job for the captured
site. **Idempotent**: re-setup must not spawn a second job (key on the provisioning row /
existing job for the workspace). Execution path: reuse the shipped job-row + `design_job`
fleet-task single-txn pattern (the platform composes the design fleet post-Part-II);
verify the live worker executes kind=`website` jobs in our composed stack before wiring —
if only the lumen_api service worker executes them, trigger via a server-side HTTP call to
the design API instead (never from the browser). `brand_id` lands via the
exactly-one-brand heuristic on this path (verify with a test asserting the born kit's
`brand_id` equals the provisioned brand). Tests: DB-gated — job enqueued once; idempotent
replay; brand_id stamped. Commit.

### Slice 3 — The checklist row goes real
`setup-items.ts`: bind `BRAND_KIT_ITEM_ID` to live ingestion-job status (job pending/
running → `running`; kit published → `complete`; job failed → the row's designed failure
state; no job → `queued`). Backend: extend `GET /stage0/setup/current`'s payload with the
brand-kit job status (read `design_ingestion_job` by workspace — a small, honest
extension; record it in the onboarding contract doc + the supersession note at
`FI-onboarding-contract-gap-review.md:140`). Tests: reducer per status; wire-shape. Commit.

### Slice 4 — Manual trigger + approval (⚠️ founder UI gate)
The dummy has **no ingest-trigger and no approve affordance** — both are new user-visible
elements, which the parity constitution forbids without a founder ruling on their exact
placement/appearance. **STOP-AND-ASK point: present the founder 2–3 concrete placements**
(e.g. header-right action button per the header's existing button idiom; kebab item) with
screenshots, get the ruling, then build:
- **Manual re-ingest** (ruling 2): fires the same website-ingestion enqueue with an
  **explicit `brand_id`** (multi-brand workspaces — never the heuristic); disabled while a
  job runs.
- **Approve**: `POST /api/clue/design/brand-kits/{id}/approval` via BFF; the screen
  reflects `approval_status` honestly (draft/generated_unreviewed/approved).
Tests: trigger idempotence while running; approval state round-trip. Commit.

### Slice 5 — Approved kit themes NEW documents
Per ruling 4 (stamp-at-creation, never render-fallback): at web-document creation
(`lumen_api` document-create path and/or the platform's document-creating tools — find ALL
creation sites; the gallery lane may add one), when the workspace('s brand) has an
**approved** kit and the request carries no explicit kit ref, stamp
`web_doc.theme.brand_kit = {id, version}` with the latest **approved** version. Existing
documents untouched; documents born before approval keep platform-default (record this
consequence in the contract doc — re-stamping old docs is future work / a manual action).
Tests: new doc post-approval carries the ref and its `/web/theme` serves kit tokens; new
doc pre-approval doesn't; existing doc unchanged after approval. **Browser proof:** ingest
→ approve → create new doc → open in the editor → the W4.0 color picker lists the
client's real brand tokens. Commit.

### Slice 6 — Vision-on default + close-out
Flip `lumen_ingestion_vision`/`lumen_ingestion_describe` defaults for our deployments
(env/config layer — NOT by editing the subsystem's config defaults if the house style is
env-override; follow how other lumen flags are set in our launch/env recipes; requires
`OPENROUTER_API_KEY` present — fail-soft to deterministic extraction when absent, which
the pipeline already does). Record in the launch recipe. Full-repo gates (`apps/frontend`
npm gate + root `make check`). `_memory/` close-out note. Final commit; tell the founder —
they merge/push.

## 7. Verification environment

- Launch recipe: `_memory/2026-08-17-w01-shell-lift-file-set.md` (§launch recipe) —
  platform API 8030, design API 8010 (**MANDATORY `LUMEN_CORE_HELPER`** prebuilt release
  binary — without it every engine call pays ~1.1s cargo spawn), frontend 3030 with the
  documented shell overrides. **ALWAYS `lsof -nP -iTCP:<port> -sTCP:LISTEN` and kill stale
  listeners first** — a stale pre-commit next-server on 3030 cost the trunk session a
  false "feature broken" alarm (EADDRINUSE dies silently in the log).
  Pick a fresh port trio if 3030/8030/8010 are in use by the trunk workspace.
- Test login (dev Clerk): `/onboarding/sign-in-email` →
  `onboarding+clerk_test_20260814@example.com` / `pass@123` → code `424242` → workspace
  `ws_8040294627e146ae93f753ec0d3e1726`. **For slice 2's auto-trigger you need a FRESH
  first-time onboarding** — provision a new synthetic account through the real sign-up
  flow rather than reusing this one.
- Ingestion worker needs Playwright browsers where it runs (tier-2 rendered capture is a
  lazy import — install once, or accept tier-1-only and say so in the report).
- Browser automation: the gstack `/browse` skill (headless daemon), never
  `mcp__claude-in-chrome__*`.
- Repo lint traps (each cost a prior session a loop): frontend test runner is
  `tsx --test` (NOT vitest); no sync `setState` in effects; no render-time ref writes;
  presentation components must not import `data/`/engine (seam lint); don't shadow the
  `document` global; `public/vendor/**` is gitignored build output.

## 8. Coexistence with the other lanes

Running in parallel with: the W4 schema lanes (editor inspector files — no overlap) and
the gallery leg-derived-feed worktree (chat router + gallery feature — no overlap except
**both this lane's slice 5 and the gallery lane touch document-creation surfaces**: check
whether the gallery lane's create affordance landed before wiring slice 5, and cover its
creation site too if so). Shared files with low conflict risk: `package.json` (this lane
adds two deps), `stage0_setup.py` + onboarding feature (this lane only),
`globals.css` (possible two-class addition). Rebase early, merge back one lane at a time.

## 9. Out-of-scope register (recorded, not forgotten)

1. L2 `BrandContextCard` digest (ruling 6) — FI-production-context §2.3 owns it.
2. Tone/voice LLM extraction from scraped site copy → `BrandConstraints.tone` (cheap,
   real extension point; needs its own ruling).
3. PDF + asset-upload ingestion UI (endpoints shipped; API-only until a designed surface).
4. Persistence for the dummy's client-side edits (rename/delete/font-upload/markdown
   editing) — proposed endpoints stay proposed in the lifted contract doc.
5. `design_brand_kit.brand_id` NOT NULL promotion (Part III / D3 owns it).
6. Re-theming EXISTING documents after approval (manual/batch action, future ruling).
7. Brand-studio surface beyond this page (PD-part2 O2's product note; founder Figma
   screenshots not in-repo).

**Done means:** a brand-new client signs up with just a name and website; by the time they
finish onboarding, a draft brand kit extracted from their site is waiting on the
Brand-context page (checklist row told them honestly); they review colors/typography/assets,
approve; every web page the platform generates for them from then on renders — and edits,
in the co-founder's editor with the real token picker — in their own brand.
