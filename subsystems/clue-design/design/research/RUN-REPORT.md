# Cursor Brand-Kit Ingestion — Run Report

**Brand:** Cursor (Anysphere, Inc.) · **Source:** cursor.com
**Pipeline:** lumen brandkit ingestion v1, **rendered tier** (Playwright chromium, headless, 1440×2000 viewport, full-page screenshots)
**Captured:** 2026-07-05 (run on 2026-07-06) · **Kit validates:** `validate ok: True`

> ⚠️ **Headline finding for the design-doc author:** the *current* cursor.com is a **LIGHT / cream marketing site**, not dark. Do not treat `dark_colorway: "captured"` as "the site is dark" — it only means a dark colorway was *also* found in CSS custom props. Captured `surface.page = #F7F7F4` (cream) with `text.primary = #26251E` (near-black). Role assignment is correct for a light site. See §5.

---

## 1. Pages captured (5, all rendered tier, all real content)

| Slug | URL | Rendered result | Screenshot (assets/screenshots/) |
|------|-----|-----------------|-----------------------------------|
| `/` (landing) | https://cursor.com | ✅ real, light hero "Cursor is your coding agent…" | `bf0e849b8136__screenshot.png` (2.9 MB) |
| `/pricing` | https://cursor.com/pricing | ✅ real, Hobby/Individual/Teams/Enterprise tiers | `027842423c84_pricing_screenshot.png` |
| `/enterprise` | https://cursor.com/enterprise | ✅ real, "Develop enduring software at scale" | `0ebc0520d9da_enterprise_screenshot.png` (2.0 MB) |
| `/students` | https://cursor.com/students | ✅ real, "Empowering the next generation…" | `47a740ec7563_students_screenshot.png` |
| `/blog` | https://cursor.com/blog | ✅ real, blog index + customer stories + videos | `ce8c545d148c_blog_screenshot.png` |

All five screenshots were visually verified: genuine Cursor marketing pages, light-themed, dark text, black CTA pills, Cursor-orange accents. No bot-wall, no consent page, no error page in the final set.

## 2. Counts

| Metric | Value |
|--------|-------|
| Assets dumped (asset-index.json) | **95** — 5 screenshots, 1 font, 20 logos, 69 images |
| Files on disk | 57 images, 16 logo/icon SVGs+PNGs, 1 font, 5 screenshots |
| Colors observed | **1,543** |
| Color clusters (deduped) | **20** |
| Type samples | **86** |
| Font families in evidence | **19** |
| CSS custom properties captured | **294** |
| Images (evidence) | 46 |
| Logos (evidence) | 4 |
| Shadows / raw numbers | **0** (see anomalies §6) |

## 3. Color system — top clusters (by weight)

`theme` below is the pipeline's own light/dark tag on the cluster; nearly everything is `light`.

| # | Hex | Weight | Role hints (CSS custom-prop provenance) |
|---|-----|--------|------------------------------------------|
| 1 | **#26251E** | 1352.7 | `--color-theme-fg`, `--prose-headings`, `--color-theme-button-bg` — primary ink / near-black |
| 2 | **#F7F7F4** | 635.0 | `--color-bg`, `--color-theme-bg`, `--color-white` — page cream background |
| 3 | **#F54E00** | 147.0 | `--color-accent`, `--color-warning`, `--color-theme-accent` — **Cursor orange (brand)** |
| 4 | **#F2F1ED** | 83.5 | `--color-bg-elevated`, card/chrome surfaces |
| 5 | **#1F8A65** | 82.5 | `--color-success`, ansi-green |
| 6 | **#CF2D56** | 51.0 | `--color-error`, ansi-red |
| 7 | **#3B3A33** | 47.5 | `--color-theme-button-hover-bg`, `--color-theme-fg-02` |
| 8 | **#000000** | 41.8 | `--color-black`, body-text |
| 9 | **#FFFFFF** | 26.5 | `--color-white`, ring-offset |
| 10 | **#9FBBE0** | 9.0 | `--color-timeline-read` (agent-timeline blue) |
| 11 | **#9FC9A2** | 9.0 | `--color-timeline-grep` (agent-timeline green) |
| 12 | **#C0A8DD** | 9.0 | `--color-timeline-edit` (agent-timeline purple) |
| 13 | **#DFA88F** | 9.0 | `--color-timeline-thinking` (agent-timeline peach) |
| 14 | **#E1E0DB** | 9.0 | `--color-theme-card-04-hex` |
| 15 | **#888783** | 8.5 | link / button-text / body-text — mid grey |
| 16 | **#3A6A9F** | 0.5 | (unhinted) |
| 17 | **#8BC4F8** | 0.5 | (unhinted, light) |
| 18 | **#828282** | 7.5 | link / button-text — **theme=dark** |
| 19 | **#EDECEC** | 1.0 | theme=dark |
| 20 | **#8BC4F8** | 0.5 | theme=dark |

**Palette summary:** cream/ink neutral base (#F7F7F4 bg, #26251E ink), single hot brand accent **#F54E00 (Cursor orange)**, semantic green #1F8A65 / red #CF2D56, plus a 4-hue pastel "agent timeline" set (blue/green/purple/peach). The 294 CSS custom props also expose an OKLAB/LAB blue ramp (`--color-blue-50/600/800/900`) and `color-mix()` borders (`--color-border = color-mix(in oklab, #26251e 10%, transparent)`).

## 4. Typography

**Primary marketing font: `CursorGothic`** — Cursor's custom typeface. Also present: `berkeleyMono` (mono/code), `EB Garamond` + `Lato` (blog/prose, Google-hosted), a full `KaTeX_*` math-font family (blog math), and `CursorIcons16` (icon font).

### Type scale (normalized tokens, all CursorGothic)
| Token | Size px | Weight | Line-height |
|-------|---------|--------|-------------|
| type.display | 41.5 | 700 | 1.05 |
| type.stat | 32.5 | 700 | 1.0 |
| type.headline | 26.0 | 400 | 2.03 |
| type.subtitle | 15.0 | 500 | 1.3 |
| type.title | 14.0 | 400 | 1.31 |
| type.cta | 14.0 | 400 | 1.31 |
| type.body | 12.0 | 400 | 1.5 |
| type.body.small | 10.5 | 400 | 1.4 |
| type.label | 10.0 | 600 | 1.2 |
| type.caption | 9.0 | 500 | 1.35 |
| type.eyebrow | 9.0 | 600 | 1.2 |
| type.legal | 8.0 | 400 | 1.3 |

Raw type samples (86) for CursorGothic span real marketing sizes **14 / 16 / 22 / 26 / 36 / 52 / 72 px**.

### Font families and file-download status
| Family | Role | Faces / weights | Face URLs in evidence | woff2 on disk? |
|--------|------|-----------------|-----------------------|-----------------|
| **CursorGothic** | primary display/body | 4 (400, 700 · roman+italic) | ✅ `cursor.com/media/CursorGothic_{Regular,Italic,Bold,BoldItalic}-*.woff2` | ❌ **not downloaded** |
| berkeleyMono | mono / code | 2 (400 · roman+oblique) | ✅ `cursor.com/media/BerkeleyMono_*.woff2` | ❌ not downloaded |
| CursorIcons16 | icon font | 1 (400) | ✅ `cursor.com/marketing-static/fonts/cursor-icons-16.woff2` | ✅ `d295cbdbb0e6_cursor-icons-16.woff2` |
| EB Garamond | blog prose | 70 faces (400–800) | ✅ Google Fonts | ❌ not downloaded |
| Lato | blog prose | 20 faces (100–900) | ✅ Google Fonts | ❌ not downloaded |
| KaTeX_* (13 families) | blog math | various | ✅ | ❌ not downloaded |

**Font anomaly (see §6):** every real font family, including CursorGothic, is fully captured as *evidence* (family, weight, style, source URL) but only the icon font's binary was downloaded. `@font-face src` URLs are not being fetched by the rendered-tier asset collector — only preloaded/`<link>`-referenced fonts are. The CursorGothic URLs are in `tokens/cursor-design-tokens.yaml → raw_evidence.font_faces` if the design-doc author wants the actual woff2 files.

## 5. Color-role assignments (ingestion-report.json) — light-theme, correct

| Token | Value | Basis |
|-------|-------|-------|
| surface.page | **#F7F7F4** (cream) | evidence · body |
| surface.card | #F7F7F4 | evidence · body |
| surface.brand | **#F54E00** | evidence · `--color-accent` |
| surface.accent | #1F8A65 | evidence · `--color-success` |
| surface.inverse | #121210 | derived |
| text.primary | **#26251E** (ink) | evidence · body |
| text.secondary | #57564E | derived |
| text.brand / text.accent | #952C00 | derived (darkened orange) |
| border.default | #C3C3C0 | derived |
| focus.ring / border.brand | #F54E00 | derived |

This is a clean, sensible LIGHT-theme assignment — page is light, text is dark, brand orange maps to `surface.brand`/`focus.ring`. **No odd/inverted role assignments.** The task's dark-theme caveat does not apply to the current cursor.com.

## 6. Anomalies & troubleshooting

1. **cursor.com is light, not dark** — the task briefed a likely dark theme. The live 2026 redesign is a cream/ink light site. `dark_colorway: "captured"` = a dark colorway exists in CSS vars, not that the rendered site is dark. Roles were assigned from the light body correctly.
2. **`/about` is a soft-404** — `curl -sI /about` returned HTTP 200, but the *rendered* page is Cursor's client-side "The page you're looking for has wandered off" 404. My first two runs captured it and it (a) injected a cyclic CSS custom-property that crashed the color parser, (b) pulled in stray icon fonts (codicon/seti), and (c) polluted clusters (162 vs the real 20). **Fixed by swapping `/about` → `/blog`** (verified real content, `soft404=False`) in the runner's `PAGES` list. `/features` and `/en-US` both redirect to the landing (duplicates), `/agents`/`/security`/`/careers` render Cloudflare challenge or soft-404 headless — avoid.
3. **Two shipped-package parser crashes, fixed by runner-local monkeypatch** (never edited the capture package, per task rules):
   - `parse_color_value()` recurses on `var()` with no cycle guard → `RecursionError` on the /about cyclic var. Patched with a depth-bounded (`_MAX_VAR_HOPS=24`) wrapper; identical behavior for non-cyclic values.
   - `_parse_alpha()` does `float(token)` and dies on Tailwind colors whose alpha is itself a var, e.g. `rgba(24 24 27 / var(--tw-text-opacity))`. Wrapped to treat non-numeric alpha as opaque (255). Both patches also protect against similar constructs on the real pages.
4. **`evidence.numbers` and `evidence.shadows` are empty (0).** The rendered-tier evidence builder extracted no raw spacing/radius/shadow numbers, so `raw_evidence.spacing_radius_samples` in the YAML is empty. **Yet the normalizer still emitted a full spacing (0–64 px 4-pt scale) + radii (2/4/8/12/16, full) + stroke + opacity token set — these are DERIVED DEFAULTS, not evidence-backed.** Treat spacing/radius tokens as sensible defaults, not measured from cursor.com. Colors (1,543 observed) and typography (86 samples) *are* strongly evidence-backed.
5. **5× `LUMI0508` networkidle-timeout warnings** (one per page) — non-fatal; capture proceeds after the wheel-scroll pass. Full-page screenshots are complete and show fully-rendered content, so **no timeout bump was needed** and `rendered.py` was left untouched.
6. **Asset-token gaps** (`logo.wordmark`, `logo.reversed`, `asset.illustration.primary`, `asset.texture.subtle`, `asset.icon.primary` not populated) — expected: Cursor renders its wordmark as inline SVG/text, so no standalone wordmark file was isolatable.

## 7. Runner adjustments made

Only `design/research/run_cursor_ingest.py` was edited (all per task rules):
- **`PAGES`**: `/features` (redirect) and `/about` (soft-404) removed; final list = `/`, `/pricing`, `/enterprise`, `/students`, `/blog`.
- **Monkeypatch** `lumen_ingestion.capture.parse.parse_color_value` — depth-bounded var() resolution (cycle guard).
- **Monkeypatch** `lumen_ingestion.capture.parse._parse_alpha` — non-numeric alpha → opaque.
- No UA change was needed (no bot-wall on the chosen pages). `rendered.py` and the rest of the capture package were **not** modified.

## 8. Five most representative screenshots/images for a human to review

1. `design/assets/screenshots/bf0e849b8136__screenshot.png` — **landing page**, the canonical brand statement (cream hero, product editor mock, logo wall).
2. `design/assets/screenshots/027842423c84_pricing_screenshot.png` — **pricing**, cleanest view of card surfaces, tier chips, black CTA pills, theme toggles.
3. `design/assets/screenshots/0ebc0520d9da_enterprise_screenshot.png` — **enterprise**, stat blocks (64% / 50,000+ / 100M+), muted card grids, trust badges.
4. `design/assets/screenshots/ce8c545d148c_blog_screenshot.png` — **blog**, editorial/EB-Garamond prose treatment + customer-story + video modules (distinct type system from marketing).
5. `design/assets/images/0b0e25bcdae8_cursor-wallpaper.png` — **cursor-wallpaper.png** (1.4 MB, largest asset), the hero brand illustration/wallpaper.

Bonus logo assets worth a look: `design/assets/logos/c59dc1facb6a_berkeley.svg` (+ `berkeley-dark`) and the partner/university SVGs under `design/assets/logos/`.

---

## Output paths (all under `design/`)

- **Tokens YAML (rich raw_evidence):** `design/tokens/cursor-design-tokens.yaml`
- **Brand kit JSON (validated):** `design/tokens/cursor-brand-kit.json`
- **Evidence:** `design/research/evidence.json`
- **Ingestion report:** `design/research/ingestion-report.json`
- **Diagnostics:** `design/research/diagnostics.json`
- **Asset index:** `design/research/asset-index.json`
- **Per-page snapshots:** `design/research/snapshots/{landing,pricing,enterprise,students,blog}.json`
- **Asset store (content-addressed):** `design/research/asset-store/`
- **Screenshots:** `design/assets/screenshots/` (5)
- **Images:** `design/assets/images/` (57) · **Logos:** `design/assets/logos/` (16) · **Fonts:** `design/assets/fonts/` (1)
