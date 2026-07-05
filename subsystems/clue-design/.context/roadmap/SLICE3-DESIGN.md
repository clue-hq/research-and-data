# Slice 3 design — asset uploads + description engine + kit metadata fields

Implementation spec for Brand-kit Ingestion v1 slice 3 (plan §6.5/§6.6/§7; slices 0–2 shipped
`444ec7c`/`da6df84`/`487e82f`). **The engine half is ALREADY DONE in the working tree** (not
yet committed): `LogoAsset`/`BrandAsset` gained `title: Option<String>` + `description:
Option<String>` (`serde(default, skip_serializing_if)` — old serializations byte-identical),
all lumen-core tests pass, helper + WASM rebuilt. Python agents build on that.

## 0. Module layout & ownership

```
apps/api/lumen_ingestion/capture/uploads.py    # Agent A — file analysis → BrandEvidence
apps/api/lumen_ingestion/describe.py           # Agent A — description engine
apps/api/lumen_ingestion/evidence.py           # Agent A — additive IR fields (§1)
apps/api/lumen_ingestion/normalizer/emit.py    # Agent A — stamp title/description into kit assets
apps/api/migrations/008_asset_descriptions.sql # Agent A
apps/api/tests/test_ingestion_uploads.py       # Agent A
apps/api/tests/test_ingestion_describe.py      # Agent A
apps/api/lumen_ingestion/pipeline.py           # Agent B — run_asset_ingestion + describer hook in ALL 3 paths
apps/api/lumen_api/main.py                     # Agent B — POST /brand-kits/ingest/assets
apps/api/tests/test_ingestion_uploads_route.py # Agent B
```
Agent A: no pipeline.py/main.py. Agent B: no capture/, describe.py, evidence.py, emit.py,
migrations. Contracts in §1/§4.

## 1. Contracts + IR additions (Agent A implements; Agent B consumes)

Additive optional fields (schema_version stays 1; all default None/[]):
```python
class LogoEvidence:  # +
    title: str | None = None
    description: str | None = None
    usage_note: str | None = None
    tags: list[str] = []
class ImageEvidence:  # + same four fields
```

```python
# capture/uploads.py
@dataclass
class UploadFileInput:
    filename: str
    content_type: str | None
    data: bytes

def analyze_uploads(
    files: list[UploadFileInput],
    *,
    core: Any,               # CoreClient-shaped
    store_root: str,
    reporter: Callable[[str, float], None],
) -> tuple[BrandEvidence, list[dict]]   # (evidence, diagnostics LUMI07xx)

# describe.py
@dataclass
class DescribeItem:
    asset_id: str
    kind: str                 # logo|image|icon|illustration|photo
    image_b64: str            # downscaled preview (≤512px longest side, JPEG/PNG)
    filename: str | None
    context: str              # e.g. "brand: Insight Health; source: upload"

@dataclass
class DescribeResult:
    asset_id: str
    title: str                # ≤ 60 chars
    description: str          # 1–2 sentence literal visual caption (ploy-style)
    usage: str                # design-usage guidance ("use on dark backgrounds…") — our ploy-beating field
    tags: list[str]

class AssetDescriber(Protocol):
    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]: ...

class NullDescriber:  # returns [None]*len — the default everywhere incl. tests
class OpenRouterDescriber:  # §3

class DescriptionStore:  # sqlite, takes Connection
    def get_many(self, asset_ids) -> dict[str, dict]
    def put_ai(self, result: DescribeResult, model: str) -> None      # never overwrites origin='human'
    def put_human(self, asset_id, title, description, usage, tags) -> None   # slice-4 will call this
def apply_descriptions(
    evidence: BrandEvidence,
    *,
    connection: sqlite3.Connection,       # for DescriptionStore (cache + persistence)
    describer: AssetDescriber,
    resolve_bytes: Callable[[str], tuple[bytes, str] | None],   # asset_id -> (bytes, mime) or None
    reporter: Callable[[str, float], None],
) -> BrandEvidence   # returns evidence with title/description/usage_note/tags stamped on logos+images
```
`apply_descriptions` flow: collect logo+image asset_ids → cache hits from DescriptionStore
(any origin) stamp directly → misses with resolvable bytes → downscale via Pillow (lazy
import) → ONE describer.describe() call in batches of ≤ 8 → put_ai + stamp. Describer
failure/None → skip silently (evidence unchanged) + one LUMI0803 info. Stage:
reporter("Describing your assets…", 0.80). Deterministic with NullDescriber.

`resolve_bytes` (Agent B provides in pipeline): via `Repository.require_asset_record` →
`media.location.opaque_ref` → `resolve_store_path` (see main.py get_asset_bytes ~2566 for the
exact pattern; import resolve_store_path from wherever main.py gets it).

## 2. `uploads.py` (Agent A)

Accepted types by magic bytes: PNG (\x89PNG), JPEG (\xFF\xD8), WebP (RIFF….WEBP), SVG
(first 512 bytes contain `<svg` after optional decl/whitespace/comments). Others → LUMI0701
warning, file skipped (never fails the batch; ALL skipped → raise ValueError → job fails
with a clear message). Cap 20 files (LUMI0702 + skip beyond).

Per raster file (Pillow, lazy):
- dims; transparency = has alpha channel AND min alpha < 250; DPI from info.get("dpi");
  colorspace = mode.
- Dominant colors: thumbnail to ≤128px, quantize (adaptive, 8), take palette entries by pixel
  share ≥ 4%, drop fully-transparent bins; RENDER against white for alpha (matches cluster
  compositing); cap 6.
- Distinct-hue count over dominant colors (OKLCH hue buckets of 30° for entries with C≥0.07).

Classification (deterministic; priority order):
1. filename contains "logo" (case-insens) → logo.
2. SVG → logo if viewBox/width≈height ratio in [0.5, 2] else illustration; "icon" in filename
   or rendered box ≤ 128 → icon.
3. transparency AND dominant colors ≤ 6 AND min(dims) ≤ 800 → logo.
4. JPEG OR (no transparency AND min(dims) ≥ 800 AND dominant colors ≥ 6) → photo.
5. else → illustration; "screenshot"/"screen" in filename → screenshot.

Logo variant hint: opaque-pixel mean L > 0.82 → color_mode_hint "reversed" (light mark meant
for dark bg; background_hint "#121212"); distinct hues ≤ 1 AND all dominant C < 0.07 →
"one_color"; else "full_color". usage_hint: "mark" when squarish (ratio in [0.8,1.25]) AND
min(dims) ≤ 512, else "primary".

SVG handling: ingest the ORIGINAL SVG bytes as the asset (vector preserved; mime
image/svg+xml). Color analysis WITHOUT rasterizing: parse fill/stroke/stop-color attrs +
inline style declarations (regex + the hex/rgb parsers — reuse capture/parse.py helpers if
importable without cycles, else duplicate the two small parsers). dims from width/height attrs
or viewBox. No Pillow pass (transparency=None). Classification via rule 2. Note: DescribeItem
for an SVG needs a raster preview — SKIP SVGs in apply_descriptions batches (no preview
renderer in v1) with LUMI0804 info "svg preview unavailable — description skipped"; a human
can title it in the library UI.

Color evidence: dominant colors of files classified logo/icon/illustration (NOT photo — photo
palettes are scene noise) → ColorEvidence weight 2.0, hint "accent", theme light,
pointer "upload :: <filename>". Every file ingests content-addressed (`asset_ing_<sha16>`,
kind "image", tags ["brand-ingestion","upload",<classification>]).

Evidence assembly: logos → LogoEvidence (with dims/hints), non-logos → ImageEvidence
(kind_hint per classification, transparency, dominant_colors). narrative.brand_name = None
(route's `name` form field flows through the pipeline's kit-name logic instead). source:
ALL files logo-classified → `{"kind":"logo_file", asset_id:<first>, filename:<first>,
confidence:0.8}` else `{"kind":"style_guide_image", …0.7}` (serde: snake_case variants
LogoFile/StyleGuideImage exist in brand.rs:942-974).

## 3. `OpenRouterDescriber` (Agent A)

Env-gated `LUMEN_INGESTION_DESCRIBE=1`; model `LUMEN_INGESTION_DESCRIBE_MODEL` default
`anthropic/claude-sonnet-4.5`; httpx pattern copied from assist.py. ONE multimodal message
per batch: system prompt fixes the output contract (JSON array, one object per image, fields
title/description/usage/tags; description = literal visual caption — subjects, colors,
text-in-image, style; usage = one sentence of design-usage guidance incl. background
suitability, scale, pairing). Strict json_schema response; one retry; then None-per-item +
LUMI0803. Never constructed in tests.

## 4. Migration 008 + persistence (Agent A)

```sql
CREATE TABLE IF NOT EXISTS asset_descriptions (
    asset_id TEXT PRIMARY KEY,
    title TEXT, description TEXT, usage TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL CHECK (origin IN ('ai', 'human')),
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
`put_ai` uses INSERT ... ON CONFLICT DO UPDATE ... WHERE origin != 'human'. Injectable
now_iso like jobs.py.

## 5. emit.py stamping (Agent A)

- `add_logos`: LogoAsset entries gain `title`/`description` from the group's primary
  variant's LogoEvidence (title verbatim; description = caption + (" Usage: " + usage_note
  when present)); evidence tags merge → nothing (LogoAsset has no tags field — tags live in
  the description store only).
- `add_images`: BrandAsset gains title/description same way; tags merge into `style_tags`
  (deduped, sorted, prepended after existing).
- Fields OMITTED (not null) when absent — matches the Rust skip_serializing_if so golden
  snapshots without descriptions stay unchanged. Verify goldens unchanged; regenerate ONLY if
  a fixture legitimately gains fields.

## 6. Route + pipeline (Agent B)

`POST /brand-kits/ingest/assets`: `files: list[UploadFile] = File(...)`, `name`/`brand_kit_id`
Form(None). Validation: 1–20 files (422 "ingest.too_many_files" over), each ≤ asset_max_bytes
(413), magic-sniff per §2 — files failing sniff are still passed through (uploads.py skips
with diagnostics), but if NONE pass sniff → 422 "ingest.unsupported_file". Persist each to
`<store_root>/ingest_tmp/<job_id>_<idx>_<sanitized-filename>`; request_json = {files:
[{filename, content_type, tmp_path}], name, brand_kit_id}. Job kind "asset_upload". Response
+ GET reuse existing shapes.

`run_asset_ingestion(database_path, asset_store_root, job_id, *, analyze=<lazy
analyze_uploads>, describer=None)`: mirrors the other two paths; reads tmp files (missing →
LUMI0605-style fail; delete all in finally); analyze → apply_descriptions (describer =
param or `resolve_describer()`: OpenRouterDescriber if LUMEN_INGESTION_DESCRIBE=1 else
NullDescriber; resolve_bytes built from Repository + resolve_store_path per §1) → reporter
("Preparing your brand kit…", 0.85) → normalize → persist source **"asset_upload"** (in the
007 CHECK). Kit name default: request name → "Uploaded assets (<n> files)".

**Describer hook in the existing website + PDF paths (Agent B):** insert
`evidence = apply_descriptions(evidence, connection=…, describer=resolve_describer(),
resolve_bytes=…, reporter=reporter)` right after evidence is built in `_ingest` and
`_ingest_pdf` (lazy import of describe.py; with NullDescriber this is a no-op pass that
must not disturb existing tests — verify).

## 7. Tests

Agent A:
- uploads: generate tiny test images IN-TEST with Pillow (transparent teal logo PNG 200×200,
  white-on-transparent reversed mark 96×96, 1200×900 JPEG photo gradient+noise, small SVG
  string with fills) → classification, variant hints, dominant colors, color evidence
  (photo palette excluded), caps, magic rejection, all-rejected ValueError, SVG color parse +
  no-Pillow-pass, content-addressed ids (stub core records calls).
- describe: NullDescriber no-op; scripted stub describer → stamping on evidence + put_ai
  rows; cache hit short-circuits (describer NOT called for cached ids — assert call count);
  human row never overwritten by put_ai; batching (17 items → 3 calls of 8/8/1); SVG skipped;
  migration idempotence (fresh + reopen).
- emit stamping: evidence with title/description/usage/tags → kit LogoAsset/BrandAsset carry
  title/description (+style_tags merged); absent → keys OMITTED from kit JSON; goldens
  unchanged (run the snapshot suite).
- round-trip: stamped kit passes validate_brand_kit(product_ready=False) via real helper
  (proves the new engine fields).
- import hygiene: `import lumen_ingestion.describe` pulls neither PIL nor httpx.

Agent B (route/pipeline, analyzer + describer stubbed):
happy path multi-file (kit source=="asset_upload", logo + image assets in kit, summary
"ingestion" present) · name default "Uploaded assets (3 files)" · too-many 422 · oversize
413 · none-supported 422 · tmp cleanup success+failure · describer hook: stub describer
injected → descriptions appear in the persisted kit assets; website + PDF path tests still
green after the hook (run those suites).

## 8. Verification

Full: `pytest tests -q` (expect 166+new; same 3 skips). Rust side is already green; DO NOT
touch crates/. The WASM artifact is already rebuilt — editor untouched by agents.
