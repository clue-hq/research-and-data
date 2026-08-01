# Slice 2 design — brand-guidelines PDF path

Implementation spec for Brand-kit Ingestion v1 slice 2 (plan §6.4/§7; slices 0–1 shipped
`444ec7c`/`da6df84` — read SLICE0-DESIGN.md + SLICE1-DESIGN.md first). The reference input is
`/Users/aryankeshri/Documents/screenshots_and_screenrecords/brandkit/insight_health_brand_kit.pdf`
(19 pages) — COPY it into `apps/api/tests/fixtures/ingestion/insight_health_brand_kit.pdf`
(2.7 MB committed fixture; the DoD is exact-extraction regression on this file).

## 0. Module layout & ownership

```
apps/api/lumen_ingestion/capture/pdf.py         # Agent A — extraction (the meat)
apps/api/lumen_ingestion/capture/pdf_vision.py  # Agent A — PdfVisionAssist protocol + Null + OpenRouter impls
apps/api/lumen_ingestion/pipeline.py            # Agent B — add run_pdf_ingestion (additive edit)
apps/api/lumen_api/models.py / main.py          # Agent B — POST /brand-kits/ingest/pdf (multipart)
apps/api/tests/test_ingestion_pdf.py            # Agent A — extraction tests (real PDF fixture)
apps/api/tests/test_ingestion_pdf_route.py      # Agent B — route/pipeline tests (stubbed extractor)
apps/api/tests/fixtures/ingestion/insight_health_brand_kit.pdf   # Agent A copies it in
```

Agent A must not touch pipeline.py/lumen_api/*; Agent B must not touch capture/* or the PDF
tests/fixture. Contract between them is §1.

## 1. Contract

```python
# capture/pdf.py
@dataclass
class PdfExtraction:
    evidence: BrandEvidence          # source = {"kind":"uploaded_pdf", asset_id, filename, confidence:0.75}
    diagnostics: list[dict]          # LUMI06xx
    reference_asset_id: str          # the stored PDF itself
    page_count: int

def extract_pdf_evidence(
    pdf_bytes: bytes,
    filename: str,
    *,
    core: CoreClient,                # asset-store ingestion (typed Any to keep import lazy-friendly)
    store_root: str,
    reporter: Callable[[str, float], None],
    vision: PdfVisionAssist | None = None,   # None → NullPdfVision()
) -> PdfExtraction
```

`run_pdf_ingestion(database_path, asset_store_root, job_id, *, extract=<lazy default>)`
mirrors `run_website_ingestion` exactly (same job store, same persist flow, `source="pdf"`
DB value, kit id default `brand_kit_ing_<suffix>`, name = request name → narrative.brand_name
→ filename stem title-cased). PDF ingest jobs use kind `"pdf"` (already in the 007 CHECK).

## 2. Extraction pipeline (`pdf.py`) — pymupdf (fitz) only

pypdf is NOT needed — pymupdf covers text, fonts, embedded images, and rasters with one dep.
Lazy-import fitz INSIDE functions (import hygiene: `import lumen_ingestion.capture` must still
not pull pymupdf; add that assertion to the existing hygiene test pattern in your test file).

Stages (reporter): "Reading your brand guidelines…" 0.05 → "Extracting your colors…" 0.25 →
"Collecting your logos…" 0.45 → "Matching your typography…" 0.60 → (vision, when enabled:
"Studying the guidelines…" 0.70).

### 2.1 Reference asset + page model
- Ingest the PDF bytes themselves first: asset_id `asset_ing_<sha256[:16]>`, kind "document",
  label filename, tags ["brand-ingestion","reference-pdf"]. This id is `reference_asset_id`
  AND goes into evidence narrative summary_facts as `"reference_pdf:<asset_id>"` plus the
  ingestion source dict.
- Per page collect: `page.get_text("text")` (raw), `page.get_text("dict")` (spans with font,
  size, flags, color int), heading = largest-size span in the top 40% of the page (fallback:
  first span). Classify page kind DETERMINISTICALLY by heading/text keywords
  (case-insensitive): PALETTE ("color palette"|"colors" heading + ≥2 hex matches), SHADES,
  COMBINATIONS ("combination"), LOGO ("logo"~heading incl. "logotype"/"logomark"),
  CLEARSPACE ("clear space"), DONTS ("don't"|"donts"), TYPOGRAPHY ("typography"|"typeface"|
  "weights"), COVER (page 1), OTHER.

### 2.2 Colors — text layer (exact values; the DoD centerpiece)
- Regexes over per-page text:
  - hex: `#?([0-9A-Fa-f]{6})\b` following `HEX:?\s*` (require the HEX prefix OR a `#`).
  - rgb triplets: `R:?\s*(\d{1,3})\s*G:?\s*(\d{1,3})\s*B:?\s*(\d{1,3})` (Insight prints both —
    when hex+rgb adjacent agree, one ColorEvidence; disagreement → trust hex + LUMI0601 warning).
  - CMYK `C:? d+ M:? d+ Y:? d+ K:? d+` and `PANTONE\s+\S+` → attach to the nearest color as
    `role_hints += ["cmyk:<c,m,y,k>"|"pantone:<code>"]` (string hints; print work consumes later).
- NAME association: the nearest preceding text line on the same page that is short (≤ 28 chars),
  not a header/footer artifact, and title-cased-ish → ColorEvidence.name ("Mint Green",
  "Mint Green Dark", "Off White", "Ash Black", "Cold Blue", "Soft Indigo", "Light Grey").
  pointer locator `"page <n> :: <name>"`.
- Weights/hints: palette-page colors weight 4.0. Heuristic hints from name/lightness:
  name contains "white"/L>0.93 → page-bg; "black"/L<0.25 → body-text; else accent. The
  FIRST palette color (reading order) gets hint "accent" + weight 5.0 (brand books lead with
  the primary).
- SHADES page (80%/60%/40%/20% rows): do NOT emit colors; emit RuleEvidence kind
  "combination" text "shade system: 80/60/40/20% opacity steps of brand colors" +
  numeric_value None. (Opacity tokens already have fixed values in the normalizer.)
- COMBINATIONS page: sentences containing "should be displayed"/"Don't use" → RuleEvidence
  kind "combination" / "dont" respectively (verbatim text, trimmed).
- theme="dark" evidence: from logo-page dark panels (§2.4) — the dominant dark panel color →
  ColorEvidence(theme="dark", role_hints=["page-bg"], weight 3.0). Named palette colors stay
  theme="light".

### 2.3 Typography — text layer + font resources
- `page.get_fonts()` across pages → embedded font basenames (e.g. "AeonikTRIAL-SemiBold",
  subset prefixes like "ABCDEF+Aeonik-Regular" — strip `^[A-Z]{6}\+`). Family = basename before
  `-`; suffix → weight map (Thin 100/Light 300/Regular 400/Medium 500/SemiBold|Semi-bold 600/
  Bold 700/Black 900; unknown → 400). "TRIAL" in name → license_hint "trial-filename".
  EXCLUDE fonts that only appear on ≤2 pages AND match known doc-template families (none in
  Insight; keep the rule simple: keep all, weight by page coverage).
- FontEvidence: faces=[] with source_url=None (embedded subsets are not extractable/usable) —
  the normalizer's LUMI0230 "font files not sourced" diagnostic fires downstream (DoD).
- role_hint: family used by the LARGEST spans across content pages → "heading"; family of the
  most COMMON body-size spans (< 20pt) → "body"; same family both → heading (normalizer
  handles single-family). TYPOGRAPHY/WEIGHTS pages listing "Regular"/"Semi-bold" specimen
  labels: emit TypeSample(label="pdf-heading", family, weight=600) and ("pdf-body", family,
  weight=400) when those labels appear (sizes None — brand books rarely state UI px sizes;
  the normalizer's scale fills in).
- Span-derived type samples: for each content page, the heading span → TypeSample
  label "pdf-heading" (size_px = span size × 96/72), body spans → "pdf-body" median size.

### 2.4 Logos — embedded rasters + panel cropping (Pillow)
1. Embedded raster XObjects (`page.get_images(full=True)` on LOGO/COVER pages): extract via
   `fitz.Pixmap`; ≥ 64px shorter side → logo candidate (usage from page kind: LOGOMARK page →
   "mark", LOGOTYPE → "wordmark", else "primary").
2. Vector logos (the common case, incl. Insight): render each LOGO-classified page at 2×
   (`page.get_pixmap(matrix=fitz.Matrix(2,2))`) → Pillow: detect the demo panels — scan for
   the largest contiguous DARK region (mean luminance < 0.3) covering ≥ 15% of the page and
   the largest LIGHT region; crop each panel with 2% inset. Dark-panel crop → logo candidate
   color_mode_hint "reversed", background_hint = panel's dominant hex, PLUS the theme="dark"
   page-bg ColorEvidence (§2.2). Light-panel crop → color_mode_hint "full_color",
   usage per page kind. Register crops as PNG assets (content-addressed ids). Cap: ≤ 2
   variants per LOGO page, ≤ 6 total; each crop also carries width/height.
3. If no logo evidence at all: LUMI0602 warning "logo appears vector-only and panel detection
   failed — upload logo files separately".
Non-logo embedded images ≥ 200px (usage-example photos etc.): ImageEvidence kind_hint "photo"
(cap 8, LUMI0603 info when capped). Skip images on DONTS pages (they are counter-examples —
do NOT feed them as brand imagery).

### 2.5 Rules
- CLEARSPACE page: sentence mentioning "safe zone"/"clear space" → RuleEvidence kind
  "clearspace" (numeric only if a pt/px/mm number appears).
- DONTS page: caption lines starting with "Don't" → one RuleEvidence kind "dont" each.
- Any page: "minimum size"/"min size" + number → kind "min_size" with numeric_value.
- Tone/imagery sections when present (headings "tone of voice"/"imagery") → matching kinds.

### 2.6 Narrative
brand_name: the wordmark-ish string on the cover (largest cover span that is not
"BRAND"/"GUIDELINES" boilerplate — for Insight this is "InsightHealth"; split camel-case →
"Insight Health") else filename stem; summary_facts from INTRODUCTION/ABOUT/AIM page
paragraphs (≤ 3, each ≤ 300 chars); text_excerpt = concatenated page texts capped 3000.

## 3. `pdf_vision.py` — vision assist (protocol mirrors assist.py)

```python
class PdfVisionAssist(Protocol):
    def review(self, pages: list[PageForVision]) -> PdfVisionResult | None: ...
# PageForVision: {page_number, kind_guess, png_b64 (1x raster, JPEG-quality-ish), text}
# PdfVisionResult: optional corrections/additions, ALL re-validated deterministically:
#   page_kinds: dict[int, str]          # reclassification
#   extra_rules: list[{kind, text, numeric_value?}]
#   logo_variant_hints: dict[asset_id, {color_mode, usage}]   # only for assets we extracted
#   color_names: dict[hex, str]         # naming for unnamed palette colors
#   tone: list[str]; imagery_notes: list[str]
```
- `NullPdfVision` returns None (default; ALL tests use it or a scripted stub).
- `OpenRouterPdfVision`: gated by `LUMEN_INGESTION_VISION=1`, model env
  `LUMEN_INGESTION_VISION_MODEL` default `anthropic/claude-sonnet-4.5`, httpx pattern copied
  from assist.py OpenRouter impl, images as base64 data URLs in one multimodal message,
  strict JSON schema response, one retry then None + LUMI0604 warning "vision unavailable —
  deterministic extraction only". Never constructed in tests.
- Merge policy: vision may ADD rules/names/hints and reclassify pages; it may NOT remove
  deterministic evidence or alter extracted hex values.

## 4. Route (Agent B) — multipart, mirroring the existing asset-upload route

`POST /brand-kits/ingest/pdf`: `file: UploadFile = File(...)`, `name: Optional[str] =
Form(None)`, `brand_kit_id: Optional[str] = Form(None)`. Read bytes; enforce
`asset_max_bytes()` (413 over-limit, same message style as the asset route); require
content-type application/pdf OR filename *.pdf (else 422 code "ingest.unsupported_file");
require non-empty bytes starting with `%PDF-` (else 422 "ingest.not_a_pdf"). Create job kind
"pdf" with request_json {filename, name, brand_kit_id, size_bytes} — the PDF BYTES DO NOT go
in the job row: write them to `<asset_store_root>/ingest_tmp/<job_id>.pdf` and store that
path in request_json as `tmp_path` (run_pdf_ingestion reads + deletes it in a finally).
Register the ingest routes adjacent to the website ones (still before the kit-id GET).
Response shape identical to the website POST. GET /brand-kits/ingest/{job_id} already works
for kind "pdf" untouched.

## 5. Tests

Agent A (`test_ingestion_pdf.py`, real helper via LUMEN_CORE_HELPER, stub core where noted):
1. **Exact palette (DoD):** extract from the committed Insight PDF (stub CoreClient recording
   ingests) → the 7 named colors present with EXACT hex: Mint Green #12EAB1, Cold Blue
   #00E3E1, Soft Indigo #8080F9, Off White #F5F5F5, Ash Black #1D1C1D, Mint Green Dark
   #0FD39F, Light Grey #E3E5E4; names attached; first palette color hinted accent.
2. Fonts: family Aeonik detected; faces empty; weights include 400+600; trial hint present
   ONLY if the PDF's embedded names carry TRIAL (assert on whatever the real file yields —
   inspect once and pin it).
3. Rules: ≥ 4 "dont" rules; ≥ 1 "combination" (the Off White/Ash Black sentence); 1
   "clearspace".
4. Logos: ≥ 1 reversed-variant candidate with dark background_hint AND a theme="dark"
   page-bg ColorEvidence; light primary candidate present; caps respected.
5. DONTS-page images excluded from ImageEvidence.
6. Narrative: brand_name "Insight Health" (or "InsightHealth" — pin what §2.6 yields).
7. Full round-trip (DoD): evidence → normalize_evidence → validate_brand_kit(product_ready
   =False) ok via real helper; dark_colorway == "captured"; LUMI0230-class font diagnostic
   present in normalize diagnostics.
8. Vision merge: scripted stub adds a rule + renames a color → merged; attempt to alter a
   hex → ignored (assert unchanged).
9. Import hygiene: `import lumen_ingestion.capture` pulls neither fitz nor PIL (subprocess
   check, same pattern as slice 1).
Unit primitives (tiny synthetic PDF built in-test with fitz): hex/rgb regex agreement rule,
name association, subset-prefix stripping, weight suffix map.

Agent B (`test_ingestion_pdf_route.py`, extractor stubbed):
happy path (multipart upload → job succeeded → kit source=="pdf", summary carries
"ingestion", reference asset id surfaced in report) · not-a-pdf 422 · oversize 413 ·
tmp file cleaned up after success AND after failure · failure path (extractor raises → job
failed) · kind exposed in job dto as "pdf".

## 6. Diagnostics namespace

LUMI0601 hex/rgb disagreement (warning) · 0602 no logo extractable (warning) · 0603 image cap
(info) · 0604 vision unavailable (warning) · 0605 page classification fallback (info) ·
0606 empty/failed text layer on a page (warning; if ALL pages empty → error, job fails with
"scanned/image-only PDF not supported in v1 — vision path required").

## 7. Verification

Both suites + `pytest tests -q` full (expect 143+new, same skips). Verify the committed PDF
fixture is picked up by git LFS-less add (plain 2.7 MB file is fine). No engine changes.
