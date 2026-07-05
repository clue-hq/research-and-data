# Brand-kit Ingestion v1 — mechanism study + plan (discussion draft)

Written 2026-07-05 in the brandkit workspace (`las-vegas`, branch `agents/editing-roundtrip-v1`).
Supersedes nothing; extends `.context/roadmap/BRANDKIT-INGESTION-V1-BRIEF.md` with (a) the ploy.ai
mechanism study, (b) the moda.app display target, (c) a concrete architecture. Status: **discussion
draft — no implementation started** (per standing rule).

Evidence studied:
- `ploy-web-scraping-part.mov` (3:14, 97 frames) — ploy's "Slurp" ingestion of insighthealth.ai
- `ploy-brand-assets.mov` (1:56, 58 frames) — ploy's asset library UX
- `moda-brandkit-ingestion.mov` (2:07, 63+ frames) — moda's "Import from website" of the same site
- 6 moda.app screenshots — Insight Health brand-kit display page
- `insight_health_brand_kit.pdf` (19 pages) — representative brand-guidelines PDF
- Code survey of our existing brand-kit surface (brand.rs / apps/api / agent_runtime / editor)

---

## 1. What ploy.ai actually does (reverse-engineered from the recording)

**Trigger:** user merely names the company ("consider my company is insighthealth.ai") — ploy infers
the domain and starts "Slurping" in the background, framed as onboarding brand context.

**Observed pipeline stages (exact progress strings, ~50s end-to-end):**
1. `Loading lazy content…` (18%) — headless browser loads the URL, scrolls to trigger lazy loads
2. `Desktop styles…` (38%) → `Tablet styles…` (53%) → `Mobile styles…` (64%) — computed-style
   capture at three viewport widths
3. `Merging breakpoints…` (66%) — reconcile the three captures into responsive rules
4. `Capturing cloned screenshot…` (76–83%) — full-page screenshot (thumbnail + likely vision QA ref)
5. `Generating code…` (90–95%) — LLM reconstruction of the DOM into semantic Astro/React components

**What comes through:** brand colors (normalized into a token layer — Tailwind-style
`ploy-background-inverse` classes + an internal `rosetta-ps-*` pseudo-style token system), **font
files downloaded and self-hosted** (`public/fonts/`, @font-face rewritten to local paths), logo
SVG + favicon, all imagery (converted to .webp, filenames prefixed `slurp-…`), full copy, and the
page decomposed into named semantic sections (hero / featured-in / products / testimonials…).

**Mechanism inference (high confidence):** this is NOT a Firecrawl-style scrape. It is a
**headless-browser render (Playwright/Puppeteer-class) + multi-viewport computed-style capture +
asset download + one LLM normalization pass**. That's why the clone is interactive and the fonts
are local. Nothing in the capture layer requires a paid scraping API.

**What we should NOT copy:** the code-gen half. Ploy's product is "clone the site as editable
code"; ours is "distill a brand kit (tokens + assets) that our design agent composes with." We
want ploy's *capture* layer feeding our *token/asset* model, not a site clone.

## 1b. What moda.app's ingestion does (the counter-example: no browser at all)

Same site (insighthealth.ai), ~70s submit→kit ("This will take about a minute"). Stages, verbatim:
`Visiting your website…` → `Understanding your brand…` → `Collecting your logos…` → `Gathering
your visuals…` → `Capturing your colors…` → `Matching your typography…` → `Preparing your brand
kit…` (~3s each; "Preparing" alone ~44s — the LLM synthesis dominates wall-clock, not capture).

**Mechanism read (high confidence): raw HTML/CSS fetch + asset harvest + one big LLM pass — no
rendered-browser pixel capture.** The tells:
- Font *names* surface even when files are unavailable ("Aeonik"/"Verdana" flagged not-available
  with upload/alternative prompts) — only DOM/CSS parsing yields declared `font-family` strings.
- Full semantic hex palette incl. alpha-percent borders (`#B8B0C9B3 70%`) — stylesheet values,
  not eyedropped pixels.
- Brand description cites page-text facts (product names, "SOC 2 Type II", EHR integrations) —
  LLM over scraped text, not vision.
- Images arrive as individual `<img>`/og:image assets (headshots, product shots, an OG marketing
  tile), streaming in async — not a page screenshot. No screenshot appears anywhere.

**Dark colorway is SYNTHESIZED, not captured.** insighthealth.ai has no dark mode, yet moda ships
a fully-populated dark colorway (deep purple-navy bgs `#231D40/#2F2852/#3B3363`, shared teal
accent `#4FD3C8`) — an LLM/algorithmic companion theme built from the extracted accent + neutrals
over semantic token roles, labeled "Mention 'dark mode' to use this colorway." Light = captured;
dark = manufactured. Also AI-manufactured: description, tagline, brand values, tone chips.

**Ploy-vs-moda in one line:** ploy renders because its product is a working site clone; moda
parses because its product is a token kit. **Our product is moda's shape** — and static CSS
parsing has one capture advantage a light-mode render lacks: `@media (prefers-color-scheme: dark)`
blocks and dark-theme custom-prop overrides are readable directly from the stylesheet when a real
dark mode exists.

## 2. What ploy's asset library shows (the description mechanism)

- **Every ingested image gets an AI vision caption at ingest** — e.g. *"A 3D purple shield icon
  with a white cross, flanked by HIPAA and SOC 2 compliance badges."* — plus a short AI title
  ("Compliance and Security Shield Graphic"). Both editable (pencil icon); human corrects rather
  than writes.
- **Multi-tag taxonomy, not folders**: provenance tags (Website / User Uploaded / AI Generated /
  Figma) coexist with type/usage tags (Logos / Photographs / Ad Creatives / Screenshots / Graphics /
  Fonts); sidebar = saved filters with live counts.
- Fixed detail schema: Title, Description, Filename (read-only, `slurp-…` provenance visible),
  Type, Size, Dimensions, Created, Tags. Lightbox preview with zoom. Fonts get a live "Aa Bb"
  specimen rendered in-face.
- **Ploy's gaps (our opportunities):** captions are purely *descriptive* — no usage guidance
  (when/where to use, backgrounds, variant relationships); no logo variant modeling (dark/light/
  mono, clearspace, min-size — our `LogoAsset` already models these); fonts aren't grouped by
  family or ramped; **colors are not surfaced at all** (no palette view, no hex tokens).

## 3. What moda.app displays (our frontend target)

Brand-kit page sections, top to bottom: identity header (name, URL, **AI-written brand
description**); Logos grid (+ upload tile); Typography with **font-availability validation**
("Aeonik not available" warning → upload TTF/OTF/WOFF/WOFF2 or pick suggested alternatives
Inter/Work Sans/DM Sans; Heading vs Body role dropdowns); Colors as **light/dark colorways** with
named roles (Primary/Secondary/Tertiary/Inverted background; Primary/Secondary/Muted/Inverted
text; Text-on-accent; Primary/Secondary accent; Primary/Subtle/Focus borders — hex shown, "Set as
default" per colorway, "Other" for extras) plus loose named chips (Mint Green, Cold Blue, Soft
Indigo…); Images grid; Tagline (editable); Brand Values chips; Tone of Voice chips; Slides Theme;
**Reference Files** (the source PDF stays attached as provenance); Generated Image Styles; and
**Guides** (free-text creative-direction docs, e.g. "Logo Usage Guidelines"). Top bar: "Import
from website / Upload brand guidelines / Chat with Moda" — the same three intake paths as our
brief, plus chat.

Moda's color roles map ~1:1 onto our existing `surface.*` / `text.*` / `border.*` / `focus.*`
role names; their light/dark colorways map onto our `modes` axes (theme). Validation-with-
alternatives for fonts maps onto our `FontAsset.fallback_stack`.

## 4. The brand PDF (what path 2 must parse)

`insight_health_brand_kit.pdf` is a canonical brand book: logo / logotype / logomark on light+dark,
usage examples, **clear space** (rule expressed relative to the logo's intersection element),
**logo don'ts** (6 illustrated rules), color palette with **names + hex + RGB** printed as text
(Mint Green #12EAB1, Cold Blue #00E3E1, Soft Indigo #8080F9, Off White #F5F5F5, Ash Black #1D1C1D,
Mint Green Dark #0FD39F, Light Grey #E3E5E4), an **opacity-shade system** (80/60/40/20%),
**combination do/don'ts** ("text in Off White on 100% color backgrounds or Ash Black on opacity
backgrounds; don't use color-on-color"), and typography (Aeonik, Regular + Semi-bold specimens).
Key implication: **the exact values live in the text layer** (hex/RGB extractable without vision),
while the *rules* (clearspace, don'ts, combinations) are visual/semantic → vision pass →
`BrandConstraints` + logo metadata. Embedded logo images are extractable as assets.

## 5. What we already have (code survey summary)

- `BrandSource` enum already has variants for every path: `Website{url,captured_at,confidence}`,
  `UploadedPdf{asset_id,…}`, `StyleGuideImage`, `LogoFile`, `AgentExtract` (brand.rs:942-974).
- `TokenCatalog` + required product-ready role names enumerated as constants (brand.rs:45-167):
  43 color tokens (`palette.*`, `surface.*`, `text.*`, `border.*`, `focus.*`), 12 `type.*` roles,
  17 `space.*`, 10 `radius.*`, 8 `stroke.width.*`, 6 `opacity.*`, 7 `logo.*`/`asset.*` slots.
  These are the mandatory output vocabulary (brief's hard constraint).
- `BrandAssets`: fonts (faces, license embeddable/subsettable), logos (variants FullColor/OneColor/
  Reversed/Dark/Light, usage, min_size, clearspace, allowed_backgrounds), images (role, style_tags,
  allowed_contexts, preferred_color_tokens, recolor_allowed, crop_allowed). **No prose
  `description` field on assets today** → smallest engine change we need (additive, serde-default).
- API: `/brand-kits` CRUD + `/brand-kits/generate` + `/brand-kits/compile-styles` (raw CSS/SCSS
  string → compiled kit — the normalization head start the brief names) + validate/compatibility +
  `/documents/{id}/brand-kit` attach. `brand_kits` table already has `approval_status`,
  `product_ready`, `source`, `brand_summary_json`, `diagnostics_json`.
- Asset store: `ingest_asset(bytes_base64, label, kind, provenance, tags…)` exists.
- Python deps: httpx only. **No playwright / pypdf / Pillow / fonttools / bs4 — all greenfield.**
- No Firecrawl integration exists in the repo (it's only available as a session skill here).
- Frontend: `BrandKitPanel.tsx` (attach/validate inside editor) exists; no kit display page, no
  asset library.

---

## 6. Recommended architecture

### 6.0 The scraping decision: tiered capture — static fetch first, Playwright as escalation

Firecrawl is out either way (credits, wrong output shape). Between the two observed pipelines:

| | ploy (render) | moda (fetch+parse) |
|---|---|---|
| Capture | headless browser, 3 viewports, computed styles | raw HTML + linked CSS, DOM parse |
| Gets | cascade-resolved styles, area-weighted colors, lazy content, screenshot, SPA support | declared font names (+ graceful "not available"), CSS custom props, exact hex incl. alpha, og:image/imgs, page text for narrative, dark-mode CSS blocks |
| Misses | nothing visual; heavier infra, flakier, bot-detection | client-rendered SPAs, computed cascade, visual dominance weighting, screenshot |
| Weight | chromium install, ~seconds/page, memory | httpx + parser, milliseconds/page |

Neither costs external credits — "cost" here is infra weight/latency/flakiness. Since our product
is moda-shaped (token kit, not site clone), **v1 default = Tier 1 static capture** (httpx +
selectolax/lxml + tinycss2): page HTML, linked+inline CSS, `:root`/custom props, declared rules,
`@font-face` URLs (font files downloadable without a browser), `@media (prefers-color-scheme:
dark)` overrides, og:image/link-icons/header img+svg, `<img>` harvest, page text. **Tier 2 =
Playwright render**, behind the same `PageCapturer` interface, triggered by an evidence-quality
gate (near-empty body ⇒ client-side-rendered; too few colors/type samples; no stylesheets
resolvable) — and optionally for a review screenshot. Both tiers emit the same `BrandEvidence`;
the normalizer never knows which ran. Golden fixtures = saved capture bundles (network-free tests)
per tier. Playwright stays a dependency but out of the hot path; most marketing/landing pages are
SSR'd and Tier 1 suffices (moda proves the ceiling of fetch-only quality on exactly our target
class of site).

### 6.1 One intermediate representation: `BrandEvidence`

All three intake paths produce the same normalized evidence bundle; one shared normalizer maps
evidence → draft kit. This is the load-bearing design decision: paths stay thin, mapping logic
exists once, multi-source ingestion later becomes "merge evidence" not "merge kits".

```
BrandEvidence {
  source: BrandSource,
  colors:      [{ value(hex/rgb), weight, role_hints[button-bg|body-text|page-bg|link|border…],
                  name?, evidence_ptr }],
  type_ramp:   [{ selector_or_label(h1|body|Heading…), family, weight, size, line_height,
                  letter_spacing, evidence_ptr }],
  fonts:       [{ family, faces[{weight,style,bytes/asset_id,format}], provenance, license_hint }],
  logos:       [{ asset_id, color_mode_hint, width, height, background_hint, evidence_ptr }],
  images:      [{ asset_id, dims, transparency, dominant_colors, evidence_ptr }],
  spacing_samples / radius_samples / shadow_samples,
  rules:       [{ kind(clearspace|min_size|combination|dont|tone|imagery), text, evidence_ptr }],
  screenshots: [asset_id],           # rendered page / PDF pages
  narrative:   { name?, url?, tagline?, summary_facts[] }
}
```

`evidence_ptr` = where it came from (URL+selector, PDF page, filename) → feeds
`brand_summary_json` so human review is judgeable (brief requirement).

### 6.2 Normalizer: evidence → draft kit (deterministic core + LLM assist)

- **Deterministic:** color clustering/dedup (ΔE), area/frequency weighting, type-ramp sorting,
  spacing/radius quantization, ramp *derivation* (generate `palette.primary.50…900` from an anchor
  accent via OKLCH lightness ladder — required tokens must all be emitted), contrast-checked
  text-on-surface assignments, font-face → `FontAsset` with conservative license flags
  (`embeddable=false` unless provenance says otherwise).
- **LLM assist (one structured call, vision over screenshots + evidence JSON):** role assignment
  judgment calls (which saturated color is `surface.brand` vs decorative; which family is heading
  vs body when h1 lies), brand narrative (name/description/tone — moda-style header), and
  `BrandConstraints` extraction from rules text. Output strictly validated against the required
  role-name vocabulary; anything unmappable → `aliases`/kit-local names + `diagnostics_json` gap
  records (brief's compatibility constraint).
- Every kit lands `approval_status=draft`, `product_ready=false`, `source` per path.

### 6.3 Path 1 — web scrape (tiered capture per §6.0)

Stages (worth surfacing as moda-style progress events — "Visiting… / Capturing colors… /
Matching typography…" — cheap and high-trust):
1. **Tier-1 fetch & parse:** GET page + linked/inline CSS (httpx, browser-ish UA, redirects);
   parse DOM (selectolax/lxml) + CSS (tinycss2). Extract: `:root`/custom props (design-token
   goldmine when present), declared color/background/border rules mapped to selector role hints
   (button/a/nav/body/h1…), font-family declarations per heading/body selectors, `@font-face`
   rules, `@media (prefers-color-scheme: dark)` overrides (real dark-mode evidence when present),
   spacing/radius/shadow declarations, page text (for narrative), `<title>`/meta/og tags.
2. **Evidence-quality gate → Tier-2 render (Playwright)** only if Tier 1 is starved (client-
   rendered SPA, few colors/type samples): load desktop 1440w, settle, auto-scroll lazy content,
   computed-style sweep with on-screen-area weighting, full-page screenshot → asset store (review
   thumbnail + vision input). Same `BrandEvidence` out.
3. **Asset harvest (both tiers):** `@font-face` URLs → download font files (woff2/ttf) → asset
   store (no browser needed); logo heuristics (header/nav img+svg, og:image, apple-touch-icon,
   favicon) → logo candidates with color-mode hint from surrounding declared background;
   `<img>`/inline-svg above size threshold → images (dedupe by content hash, async like moda's
   streaming grid).
4. Evidence → normalizer. Optionally seed `compile_styles_brand_kit` input from harvested CSS
   custom props (reuse, don't reinvent).
5. **Graceful degradation is a feature** (moda's lesson): fonts named but not sourced → kit entry
   with empty faces + "upload or pick alternative" diagnostic; weak palette → platform-default
   backfill + diagnostic. Never hard-fail an ingest that got *something*.

### 6.4 Path 2 — brand-guidelines PDF

1. Upload PDF → asset store (kept as Reference File on the kit, moda-style).
2. **Text layer** (pypdf/pdfplumber): exact hex/RGB/CMYK/Pantone strings + color names, font
   names, numeric rules — precise values for free.
3. **Page rasters** (pdfium/pymupdf render) → vision LLM pass: page classification (palette page /
   logo page / typography / don'ts / combinations), rule extraction (clearspace, min size,
   allowed backgrounds, combination do/don'ts → `BrandConstraints` + `LogoAsset` fields — the
   model has exact fields for these), shade/opacity systems → `opacity.*` hints.
4. **Embedded image XObjects:** extract; logo-looking ones (aspect, transparency, page context) →
   logo assets with variant hints (the Insight PDF has light+dark lockups, logotype, logomark).
5. Note: brand PDFs name fonts but rarely embed usable font files → font entries created with
   `faces[]` empty + a **"font file missing — upload or pick alternative"** diagnostic (feeds the
   moda-style validation UI).

### 6.5 Path 3 — individual asset uploads (SVG/PNG/JPG)

1. Register into asset store; raster metadata via Pillow (dims, DPI, colorspace, transparency);
   SVG kept as vector asset (also rasterized for analysis/preview).
2. Analysis: dominant palette (accent candidates), monochrome/duotone detection, edge/photo-vs-
   flat-graphic heuristics + **vision classification**: logo vs illustration vs photo vs icon;
   for logos: variant guess (dark/light/mono) from palette + transparency.
3. Uploads *enrich* the workspace's draft kit (add assets + accent-color evidence); they don't
   have to mint a whole kit alone — but N logo/asset uploads with no other source still produce a
   valid draft kit whose token gaps are platform-default-filled with diagnostics recorded.

### 6.6 Asset descriptions (the ploy idea, done better)

At ingest, every image/logo asset gets **one structured vision call** producing:
- `title` — short human name ("Compliance Shield Graphic")
- `description` — literal visual caption (ploy-style: subjects, colors, text-in-image, style)
- `usage` — the part ploy lacks: guidance the *design agent* needs ("use on dark backgrounds",
  "hero-scale photo", "pairs with mint accent", suggested `allowed_contexts`/`style_tags`)
- tags (provenance + type/usage, multi-tag not folders)

Storage: title/description on the asset-store record (label + new description/metadata), plus the
agent-facing bits into `BrandAsset.style_tags` / `allowed_contexts` / `preferred_color_tokens`.
**Engine ask (additive):** `description: Option<String>` on `BrandAsset` + `LogoAsset` (+ maybe
`title`) so descriptions ride the kit into the agent brief. Human-editable in the library UI;
edits are the human-gating in action. Batch the vision calls; cache by content hash (same
discipline as `image_cache.py`).

### 6.7 Frontend (⚠ scope-fence change vs the brief — needs user sign-off)

The brief fenced v1 to "API/Python only, approval UI minimal/API-only". The user now explicitly
wants moda-style kit display + a ploy-style asset library. Proposal that keeps merges trivial:
**new standalone pages** (e.g. `/brand-kits` list → kit detail → asset library), **zero editor-
canvas file changes**. Phase 3 (imaging) is editor-heavy; a new brand section is near-zero
collision. Components:
- **Kit page (moda-anatomy):** identity header (name/url/AI description), logos grid, typography
  with availability validation + upload/alternative picker, colorways with named roles + hex,
  loose palette chips, images strip, tagline/values/tone chips, reference files, diagnostics
  panel (from `diagnostics_json`), **Approve / keep-draft** gate.
- **Asset library (ploy-anatomy + our upgrades):** table/grid toggle, multi-tag sidebar with
  counts, search, sort, upload + drag-drop; detail lightbox with zoom; editable title/description/
  usage; font family grouping with live specimen + weight ramp; logo variant grouping; colors DO
  appear (as the kit's palette — ploy's gap).
- **Ingestion progress UI:** surface pipeline stage events (ploy's "Slurping… 38%" pattern) —
  cheap and high-trust.

### 6.8 Explicitly out of scope for v1 (unchanged from brief)

Agent *application* of kit assets/theme (merges into main track after Phase 3), Appearance/restyle
UI, print constraint enforcement, multi-source merge UI (later ingestions = new kit version),
content-schema anything, site code-gen (ploy's second half).

---

## 7. Work breakdown (locked 2026-07-05; each slice = one landable PR with fixtures)

Dependency spine: **0 → 1 → (2 ∥ 3 ∥ 4)**. Slice 0 is the contract everything else plugs into;
slice 1 proves the contract end-to-end on the highest-value path; 2/3/4 then fan out in parallel
(different files, no collisions). Working model per the standing delegation rule: Fable designs
interfaces + reviews; Opus/Sonnet subagents do mechanical implementation, fixtures, e2e driving.

### Slice 0 — foundations & the `BrandEvidence` contract (the thinking slice, smallest code)
- Deps into apps/api requirements: selectolax (or lxml), tinycss2, Pillow, fonttools, pypdf,
  pymupdf; playwright listed but lazily imported (Tier-2 only).
- New module `apps/api/lumen_ingestion/`: `evidence.py` (pydantic `BrandEvidence` — §6.1),
  `normalizer/` (deterministic core: ΔE color clustering, area/frequency weighting, OKLCH ramp
  derivation, contrast-checked role assignment, required-token backfill, diagnostics emission),
  `normalizer/llm.py` (single structured role-assignment + narrative + dark-synthesis call,
  validated against the required role-name vocabulary), `jobs.py` (async ingestion-job model:
  ingest runs are ~70s-class → job row + status/progress endpoint; the API is sync-CRUD today,
  this is the one new architectural piece).
- Golden-fixture harness: fixtures are saved `BrandEvidence` bundles + expected-kit snapshots;
  property test: *any* evidence in → all required role names out or explicit diagnostic.
- **DoD:** evidence JSON → draft kit passing `/brand-kits/validate` round-trip, with
  brand_summary_json evidence pointers + synthesized dark colorway marked `derived`.

### Slice 1 — web-scrape path (proves the pipe end-to-end)
- `capture/static.py` (Tier-1: fetch + DOM/CSS parse per §6.3), `capture/quality_gate.py`,
  `capture/rendered.py` (Tier-2 Playwright behind the same `PageCapturer` interface),
  `capture/assets.py` (font download, logo heuristics, img harvest, content-hash dedupe).
- Routes: `POST /brand-kits/ingest/website` → job id; `GET /brand-kits/ingest/{job_id}` → stage +
  progress (moda-style stage names) + resulting kit id.
- Fixtures: saved insighthealth.ai capture bundle (Tier-1) + one client-rendered-SPA bundle
  (gate→Tier-2); live-network e2e behind an env flag.
- **DoD (brief's bar):** real URL in → draft kit visible via `/brand-kits`, attachable to a doc,
  colors/typography actually render on canvas (4d token fidelity already resolves attached kits).

### Slice 2 — brand-PDF path (parallel after 1)
- `capture/pdf.py`: text-layer exact values (hex/RGB/CMYK/Pantone, font names) via pypdf;
  page rasters via pymupdf → vision page-classification + rules extraction (clearspace, min-size,
  combinations, don'ts → `BrandConstraints` + `LogoAsset` fields); embedded XObject extraction →
  logo/image assets; PDF kept as reference file on the kit.
- Route: `POST /brand-kits/ingest/pdf`. Fixture: `insight_health_brand_kit.pdf` → expected kit.
- **DoD:** the Insight PDF yields its 7 named colors exactly, Aeonik faces (empty, diagnosed),
  logo variants incl. dark lockups → `modes.theme=dark` evidence, don'ts → constraints.

### Slice 3 — asset uploads + description engine + the engine change (parallel after 1)
- Rust: additive `title`/`description` (serde-default `Option<String>`) on `BrandAsset` +
  `LogoAsset`; WASM rebuild (mind the wasm-drift trap — predev preflight covers it).
- `describe.py`: batched vision call per asset (title / caption / usage guidance / tags),
  content-hash cached; invoked by ALL paths (slices 1–2 gain captions when this lands).
- `capture/uploads.py`: Pillow raster analysis (dims/DPI/colorspace/transparency/dominant
  colors), SVG kept vector + rasterized for analysis, logo-vs-illustration-vs-photo
  classification, variant hints; uploads enrich the workspace draft kit.
- Route: `POST /brand-kits/ingest/assets`. Fixture: small asset set (logo SVG, PNG dark variant,
  photo, illustration).
- **DoD:** upload set → assets registered with editable title/description/usage + kit entries
  with variant/metadata fields populated.

### Slice 4 — frontend: kit page + asset library + progress (parallel after 1's kit shape is real)
- Standalone pages only (decision #1), following existing frontend practices; zero editor-canvas
  files: kit list → kit detail (§6.7 moda-anatomy incl. font-availability warnings + alternatives,
  colorway cards with Show-details/Set-default/Delete, diagnostics panel, Approve gate) → asset
  library (§6.7 ploy-anatomy + our upgrades: palette section, font family grouping + specimen,
  logo variant grouping, editable title/description/usage).
- Ingestion progress UI wired to the slice-1 job endpoint (stage strings + streaming asset grid).
- **DoD:** URL in at the UI → watch stages → review kit → edit a description → Approve →
  `approval_status=approved`; attach to a doc from the kit page.

### Merge-later (post-Phase-3, main track — unchanged)
Agent consumption: asset descriptions/usage into `_node_brief`/prompts, kit-asset placement in
designs, `$gradient.*` ingestion (MODA-EDITOR-PLAN §5.2.4).

LLM normalization + captioning reuse the existing OpenRouter adapter + cache patterns
(`image_cache.py` discipline).

## 8. Decisions

1. **Frontend scope: DECIDED 2026-07-05** — standalone brand-kit pages in this workspace, zero
   editor-canvas file changes, following existing frontend practices.
2. **Engine additive change: DECIDED 2026-07-05** — add `description`/`title` (serde-default) to
   `BrandAsset`/`LogoAsset`; WASM rebuild rides slice 3.
3. **LLM budget: DECIDED 2026-07-05** — one normalization call + one vision call per asset,
   batched + content-hash cached (~15-30 assets/typical landing page).
4. **Scraper: DECIDED 2026-07-05** — tiered capture per §6.0. Tier-1 static fetch default,
   Playwright as evidence-gated escalation, Firecrawl out entirely.
5. **Dark-mode colorway: DECIDED 2026-07-05** — three-rung ladder: (a) real dark-mode evidence
   (`prefers-color-scheme` overrides, PDF dark lockups) → capture as `modes.theme=dark` values;
   (b) no evidence → SYNTHESIZE companion dark colorway in the normalizer from extracted
   accent+neutrals over semantic roles (same LLM call), marked `derived` in diagnostics/summary;
   (c) human edits/deletes in the kit UI. (b) is on by default.

**All v1 decisions are now locked. Next step: slice-0 work plan → implementation on go-ahead.**

## 9. Risks

- **Bot-walled/JS-fragile sites:** Playwright handles most marketing pages; keep `PageCapturer`
  interface for a hosted fallback. Cookie-banner dismissal is best-effort.
- **Role misassignment** (accent vs decorative, heading vs body): mitigated by contrast checks,
  vision assist, diagnostics + human review gate — taste stays human-gated by design.
- **Font licensing:** conservative flags default; trial-font filenames (AeonikTRIAL…) should trip
  a diagnostic.
- **Required-token completeness:** ramps must be derived, not hoped for; property-test the
  normalizer (any evidence in → all required roles out or explicit diagnostic).
- **SVG logos with gradient defs:** keep vector asset; rasterize only for analysis/preview
  (gradient-token ingestion is the separate brand-import-track item from MODA-EDITOR-PLAN §5.2.4).
- **PDF variety:** brand books vary wildly; the page-classification vision pass must degrade to
  "extract what you can + diagnostics", never hard-fail.
