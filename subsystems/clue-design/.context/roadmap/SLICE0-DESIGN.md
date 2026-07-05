# Slice 0 design — `BrandEvidence` contract, normalizer, ingestion jobs

Implementation spec for Brand-kit Ingestion v1 slice 0 (see BRANDKIT-INGESTION-V1-PLAN.md §7).
Grounded in code as of `3a9ccdf`. Python 3.11+, pydantic v2 (ships with fastapi), style matches
`apps/api/lumen_api/` (from __future__ import annotations, typed, no needless comments).

## 0. Module layout

```
apps/api/lumen_ingestion/
  __init__.py            # re-export BrandEvidence, normalize_evidence, NormalizeResult
  evidence.py            # pydantic BrandEvidence IR (§1)
  colorspace.py          # sRGB↔OKLCH/OKLab, WCAG contrast, hex parse/format (§2)
  normalizer/
    __init__.py          # normalize_evidence orchestration (§3)
    cluster.py           # color clustering (§3.1)
    roles.py             # deterministic role assignment + dark synthesis (§3.2, §3.6)
    ramps.py             # palette ramp derivation (§3.3)
    typography.py        # type-ramp mapping (§3.4)
    scales.py            # spacing/radius/stroke/opacity quantization (§3.5)
    emit.py              # kit JSON assembly (§4)
    assist.py            # RoleAssist protocol + NullRoleAssist + OpenRouterRoleAssist (§5)
  jobs.py                # ingestion job store + runner (§6)
apps/api/migrations/007_ingestion_jobs.sql
apps/api/tests/test_ingestion_normalizer.py
apps/api/tests/test_ingestion_jobs.py
apps/api/tests/fixtures/ingestion/   # golden evidence bundles + expected snapshots
```

No routes in slice 0 (routes are slice 1+). Nothing imports scraping/PDF libs yet; those deps
land in requirements now but stay unimported (except Pillow may be used by tests later — not now).

## 1. `evidence.py` — the IR (schema_version 1)

All models `BaseModel` with `model_config = ConfigDict(extra="forbid")`. Hex colors normalized
to uppercase `#RRGGBB` or `#RRGGBBAA` by validators.

```python
class EvidencePointer(BaseModel):
    source: Literal["website", "pdf", "upload", "derived"]
    locator: str                      # "https://x.com :: header img", "page 13", filename, "synthesizer"
    detail: str | None = None

class ColorEvidence(BaseModel):
    value: str                        # normalized hex
    weight: float = 1.0               # relative area/frequency weight, >=0
    theme: Literal["light", "dark"] = "light"   # dark == captured dark-mode evidence
    role_hints: list[str] = []        # from: page-bg|body-text|heading-text|button-bg|button-text|
                                      # link|border|accent|custom-prop:<name>|named:<Name>|shade-system
    name: str | None = None           # author-given name ("Mint Green")
    pointer: EvidencePointer

class TypeSample(BaseModel):
    label: str                        # h1..h6|body|button|nav|caption|pdf-heading|pdf-body|...
    family: str | None = None
    weight: int | None = None         # 100..1000
    size_px: float | None = None
    line_height: float | None = None  # unitless ratio
    letter_spacing: float | None = None  # em
    pointer: EvidencePointer

class FontFaceEvidence(BaseModel):
    weight: int | None = None
    style: str = "normal"
    asset_id: str | None = None       # set when the font file was ingested into the asset store
    source_url: str | None = None
    format: str | None = None         # woff2|woff|ttf|otf

class FontEvidence(BaseModel):
    family: str
    role_hint: Literal["heading", "body", "unknown"] = "unknown"
    faces: list[FontFaceEvidence] = []
    fallback_stack: list[str] = []
    license_hint: str | None = None   # e.g. "trial-filename", "google-fonts", "self-hosted"
    pointer: EvidencePointer

class LogoEvidence(BaseModel):
    asset_id: str
    color_mode_hint: Literal["full_color", "one_color", "reversed", "dark", "light"] | None = None
    usage_hint: Literal["primary", "mark", "wordmark"] | None = None
    width: float | None = None
    height: float | None = None
    background_hint: str | None = None    # hex of observed surrounding background
    pointer: EvidencePointer

class ImageEvidence(BaseModel):
    asset_id: str
    width: int | None = None
    height: int | None = None
    transparency: bool | None = None
    dominant_colors: list[str] = []
    kind_hint: Literal["photo", "illustration", "screenshot", "icon", "og_image"] | None = None
    pointer: EvidencePointer

class NumberSample(BaseModel):
    kind: Literal["spacing", "radius", "stroke_width", "opacity"]
    value: float                      # px (opacity: 0..1 ratio)
    weight: float = 1.0
    role_hints: list[str] = []        # gap|padding|margin|section|card|button|badge|divider
    pointer: EvidencePointer

class ShadowSample(BaseModel):
    x: float; y: float; blur: float; spread: float = 0.0
    color: str = "#000000"; opacity: float = 0.15
    pointer: EvidencePointer

class RuleEvidence(BaseModel):
    kind: Literal["clearspace", "min_size", "combination", "dont", "tone", "imagery",
                  "iconography", "accessibility", "print"]
    text: str
    numeric_value: float | None = None    # e.g. clearspace px / min size px when parsed
    pointer: EvidencePointer

class NarrativeEvidence(BaseModel):
    brand_name: str | None = None
    url: str | None = None
    tagline: str | None = None
    summary_facts: list[str] = []     # short factual strings harvested from source text
    text_excerpt: str | None = None   # bounded raw text (cap 4000 chars, validator truncates)

class BrandEvidence(BaseModel):
    schema_version: int = 1
    source: dict                      # Rust BrandSource serde JSON, e.g.
                                      # {"kind":"website","url":...,"captured_at":...,"confidence":0.7}
    colors: list[ColorEvidence] = []
    type_samples: list[TypeSample] = []
    fonts: list[FontEvidence] = []
    logos: list[LogoEvidence] = []
    images: list[ImageEvidence] = []
    numbers: list[NumberSample] = []
    shadows: list[ShadowSample] = []
    rules: list[RuleEvidence] = []
    screenshots: list[str] = []       # asset ids
    narrative: NarrativeEvidence = NarrativeEvidence()
```

## 2. `colorspace.py`

Pure functions, no deps: `hex_to_rgb`, `rgb_to_hex`, sRGB→linear→OKLab→OKLCH and inverse
(standard Björn Ottosson matrices), `oklab_distance(a, b)` (euclidean in OKLab),
`relative_luminance(hex)`, `contrast_ratio(fg_hex, bg_hex)` (WCAG 2.x),
`with_lightness(hex, L)` / `with_lch(l, c, h)` (clamped back into sRGB gamut by chroma
reduction — reduce C until in gamut, epsilon 1e-4).

## 3. Normalizer

Entry point:

```python
@dataclass
class NormalizeResult:
    brand_kit: dict          # full kit JSON (engine serde shape)
    ingestion_report: dict   # evidence-pointer report (merged into brand_summary by caller/route)
    diagnostics: list[dict]  # {code, severity, message, target?} — severities: info|warning|error

def normalize_evidence(
    evidence: BrandEvidence,
    *,
    brand_kit_id: str,
    version: int = 1,
    name: str,
    created_at: str,                    # ISO date, caller supplies (no datetime.now in library code)
    assist: RoleAssist | None = None,   # None → NullRoleAssist()
) -> NormalizeResult
```

Deterministic; same evidence in → same kit out (assist may be nondeterministic, but
NullRoleAssist is not).

### 3.1 `cluster.py`
Merge colors within OKLab distance 0.03 (weighted mean in OKLab, re-render to hex; union
role_hints; sum weights; keep first `name`; keep max-weight member's exact hex as
`representative` so brand colors never drift). Ignore fully-transparent (`#....00`). Cluster
light and dark `theme` evidence separately. Output ordered by weight desc.

### 3.2 `roles.py` — deterministic assignment (light theme)
Definitions: L/C/H = OKLCH of cluster representative. "near-neutral" C < 0.03. "saturated"
C ≥ 0.07.

1. `page_bg`: highest-weight cluster with hint `page-bg`; else highest-weight near-neutral with
   L > 0.9; else `#FFFFFF` (diagnostic `LUMI0201` info "surface.page defaulted").
2. `text_primary`: highest-weight cluster with hint `body-text` and contrast ≥ 4.5 on page_bg;
   else darkest near-neutral with weight > 0; else derive `with_lightness(page_bg, 0.25)`.
   If chosen fails contrast, walk L down (light theme) in 0.02 steps until ratio ≥ 4.5;
   diagnostic `LUMI0202` warning "text.primary adjusted for contrast (was X)".
3. `brand`: highest-weight saturated cluster among hints `button-bg|accent|link|custom-prop:*`;
   else highest-weight saturated overall; else fallback `#0F766E` + `LUMI0203` warning
   "no brand color found — platform teal used".
4. `accent_secondary`: next saturated cluster with hue distance > 30° from brand, else None.
5. Named/extra clusters (has `name` or hint `named:*`) that aren't chosen above → extras list
   (emitted as `palette.extra.<slug>`, §4).

### 3.3 `ramps.py`
`derive_ramp(anchor_hex, *, neutral: bool) -> dict[str(stop), hex]` for stops
50,100,…,900,950 with OKLCH lightness targets:
`{50:.985, 100:.955, 200:.90, 300:.82, 400:.72, 500:.62, 600:.53, 700:.45, 800:.38, 900:.30, 950:.22}`.
Chroma: neutral → min(anchor_C, 0.02) flat; primary → anchor_C scaled by
`{50:.15, 100:.25, 200:.45, 300:.65, 400:.85, 500:1.0, 600:1.0, 700:.9, 800:.75, 900:.6, 950:.45}`.
Hue constant (anchor hue; neutral hue = page_bg hue if C>0.005 else 250°). Snap: replace the
stop whose L target is nearest anchor_L with the exact anchor hex (brand color appears verbatim
in its ramp). `palette.primary.*` from brand anchor; `palette.neutral.*` from page_bg/text
grays (anchor = text_primary desaturated).

### 3.4 `typography.py`
Anchors from `type_samples` (h1→headline, h2→title, body/p→body, button→cta, caption→caption).
Heading family = most-frequent family among h1/h2/h3 samples (or fonts[] with
role_hint=heading); body family likewise from body/p. One family total → both use it.
Scale fill for the 12 required `type.*` roles; sizes (px), weights, line-heights — when an
anchor exists use it, else derive from body size B (default 16) and headline H (default 32):

| role | size | weight | line_height | color | extras |
|---|---|---|---|---|---|
| display | H×1.6 | max(hw,700) | 1.05 | text.primary | letter_spacing −0.02 |
| headline | H | hw (default 700) | 1.1 | text.primary | −0.01 |
| title | H×0.72 | hw | 1.15 | text.primary | |
| subtitle | B×1.25 | 500 | 1.3 | text.secondary | |
| body | B | bw (default 400) | 1.45 | text.primary | |
| body.small | B×0.875 | bw | 1.4 | text.primary | |
| caption | B×0.75 | 500 | 1.35 | text.secondary | |
| eyebrow | B×0.75 | 600 | 1.2 | text.brand | letter_spacing 0.08 |
| label | B×0.8125 | 600 | 1.2 | text.primary | |
| cta | B | 600 | 1.2 | text.inverse | |
| stat | H×1.25 | max(hw,700) | 1.0 | text.brand | |
| legal | B×0.6875 | bw | 1.3 | text.muted | |

Round sizes to 0.5. `font_family` = heading family for display/headline/title/stat/eyebrow,
body family for the rest. `font_asset`: key into assets.fonts (§4). Value shape: `{"kind":
"style", font_family, font_size, font_weight, line_height, letter_spacing, color, font_asset}`
(letter_spacing 0.0 default; `modes: {}` — we do NOT emit accessibility variants in v1).

### 3.5 `scales.py`
Spacing (fixed values, evidence only tunes the derived roles):
`space.0=0, .1=4, .2=8, .3=12, .4=16, .5=20, .6=24, .8=32, .10=40, .12=48, .16=64` (px).
Derived: `space.stack.tight=8, .default=16, .loose=24`, `space.section` = median of
section-hinted samples snapped to the scale else 64, `space.page.margin` = likewise else 48,
`space.card.padding` = card-hinted median else 24. Radii: `none=0, xs=2, sm=4, md=8, lg=12,
xl=16, full=9999`; `radius.card` = card-hinted median snapped else 12; `radius.button` =
button-hinted else 8; `radius.badge` = 9999 unless badge-hinted. If radius evidence median
of all samples ≥ 20, bump xl to that (cap 32). Stroke widths fixed:
`hairline=0.5, thin=1, default=1, firm=2, bold=3, divider=1, card=1, focus=2`. Opacity fixed:
`disabled=0.4, subtle=0.72, muted=0.56, overlay=0.48, scrim=0.64, emphasis=0.88`. All emitted
as `{"kind":"number","value":V,"unit":"px"}` (opacity unit `"ratio"`). Evidence that deviates
hard (e.g. spacing rhythm clearly base-5) → keep base-4 emission + `LUMI0204` info diagnostic.

### 3.6 Dark colorway (`roles.py`)
If dark-theme color evidence exists (clusters with theme="dark"), assign dark roles from it by
the same §3.2 rules (dark page_bg = darkest high-weight, etc.) — provenance "captured".
Else SYNTHESIZE — provenance "derived" + one `LUMI0210` info diagnostic ("dark colorway
synthesized from light palette"):
- dark surface hue/chroma base: `C_d = min(brand_C × 0.25, 0.04)`, hue = brand hue.
- surface.page `with_lch(0.18, C_d, H)`, canvas 0.15, card 0.22, elevated 0.26, muted 0.24,
  brand = palette.primary.400, brand.subtle `with_lch(0.28, C_d×1.5, H)`, accent = accent
  brightened to L 0.75 (or primary.300), inverse = light page_bg.
- text.primary `with_lch(0.95, min(C_d, 0.02), H)` (contrast-check ≥ 4.5 on dark page, walk up),
  secondary 0.78, muted 0.62, inverse = light text_primary, brand = primary.300,
  accent = accent at L 0.8.
- border subtle/default/strong = L 0.30/0.38/0.48 at C_d; brand = primary.500;
  focus.ring = primary.400.
Every required color token gets `value.modes["theme.dark"]`. palette.* ramps get NO dark
modes (ramps are theme-invariant).

## 4. `emit.py` — kit assembly (serde shapes verified against fixtures)

Top level: `{id, version, name, description, sources: [evidence.source], provenance:
{created_by: "lumen_ingestion", created_at, updated_at: null, confidence: <overall 0..1>,
notes: [...]}, approval_status: "draft", modes: {axes: {theme:[light,dark],
density:[comfortable,compact], accessibility:[standard,high_contrast,large_text]},
defaults: {theme:"light", density:"comfortable", accessibility:"standard"}}, tokens, assets,
constraints}`.

Overall confidence: weighted mean — 0.9 if role came from hinted evidence, 0.6 unhinted
evidence, 0.3 defaulted (track per-role during assignment).

Token entry shape (all catalogs): `{"value": {"default": <V>, "modes": {...}}, "role": <str>,
"description": <str|null>, "provenance": {"source": <str>, "confidence": <float>}}`.
- Color V: `{"kind":"hex","value":"#RRGGBB"}` (alpha via 8-digit hex when evidence carries it).
- `role` strings: colors → "surface"|"text"|"border"|"accent"|"palette"|"focus" (palette.* →
  "palette", focus.ring → "focus"); typography → role suffix ("display", "headline", …);
  numbers → "spacing"|"radius"|"stroke"|"visibility".
- **provenance.source is the evidence pointer**, compact string:
  `"<pointer.source>:<pointer.locator>"` truncated to 160 chars; derived values →
  `"derived:<what>"` (e.g. `"derived:ramp(palette.primary.600)"`, `"derived:dark-synthesis"`);
  defaults → `"default:<reason>"`.
- Required sets (must ALL be present): the 43 color + 12 type + 17 space + 10 radius +
  8 stroke + 6 opacity token paths from brand.rs:45-156. Asset tokens (`logo.*`, `asset.*`,
  brand.rs:158-166) emitted ONLY for assets we actually have (see below); each missing one →
  `LUMI0220` info diagnostic "asset token <path> not populated".
- Extras: named colors → `palette.extra.<slug>` (slug: lowercase, non-alnum→`-`); aliases map
  `{"accent.primary": {"token": "surface.accent", "description": "ingestion alias"}}` plus one
  alias per extra's original name when it differs from slug.

Assets:
- fonts: key "brand" = heading font (family, source `{"kind":"webfont","family":F}` if faces
  have source_url else `{"kind":"system","family":F}`, faces (weight/style/asset_id/source_url),
  fallback_stack (evidence else ["Arial","sans-serif"]), scripts ["latin"], license
  `{name: license_hint or "unknown", embeddable: false, subsettable: false, source_url: null,
  restrictions: ["License not verified at ingestion; do not embed in print exports without
  confirmation."]}`); key "body" only when body family differs. Missing faces (PDF path) →
  faces [] + `LUMI0230` warning "font files not sourced for <family> — upload or pick an
  alternative".
- logos: group LogoEvidence by usage_hint (primary lockup → key "primary", mark → "mark",
  wordmark → "wordmark"); entry `{variants: [{name, asset_id, color_mode, width, height}],
  usage, min_size, clearspace, allowed_backgrounds, license: null, provenance}` — min_size/
  clearspace from rules evidence (`numeric_value`) else null; allowed_backgrounds default
  ["surface.page","surface.card"] (+ "surface.inverse" for reversed variants).
  Asset tokens: logo.primary → first primary variant's asset_id; logo.mark / logo.wordmark /
  logo.reversed likewise when present. Value `{"kind":"asset","asset_id":...}`.
- images: key `img.<n>` per ImageEvidence: `{asset_id, role: kind_hint or "photo", mime_type:
  null, license: null, provenance, style_tags: [], allowed_contexts: [], preferred_color_tokens:
  [], recolor_allowed: false, crop_allowed: true}`.

Constraints: `allow_gradients: true`; tone = rule texts kind=tone (else `["clear",
"professional"]`); imagery/iconography/accessibility_notes/print_constraints from matching rule
kinds (print always includes the font-embed caution); contrast_pairs:
`[{text.primary, surface.page, 4.5}, {text.inverse, surface.brand, 4.5}, {text.inverse,
surface.inverse, 4.5}]`.

`ingestion_report` (returned; slice-1 routes merge it into brand_summary_json under key
`"ingestion"`): `{schema_version: 1, source, stats: {colors_observed, clusters, fonts, logos,
images, rules}, role_assignments: [{token, value, basis: "evidence"|"derived"|"default",
pointer}...  # color+type roles only], dark_colorway: "captured"|"synthesized",
gaps: [<token paths defaulted>], narrative: {...}}`.

Diagnostic codes (new namespace `LUMI` = lumen ingestion): 02xx normalizer (defined above),
03xx assist (`LUMI0301` warning "assist unavailable — deterministic fallback"), 04xx jobs.
Shape: `{"code": str, "severity": "info"|"warning"|"error", "message": str}` and optional
`"target": {"kind":"token","path":...}`.

## 5. `assist.py`

```python
class RoleAssist(Protocol):
    def refine(self, draft: AssistDraft) -> AssistResult | None: ...
```
`AssistDraft`: clusters (hex/weight/hints/names), deterministic role assignments, type anchors,
narrative evidence, rules texts. `AssistResult`: optional overrides `{color_roles:
{token: hex}, heading_family, body_family, description, tagline, values: [str], tone: [str],
dark_overrides: {token: hex}}` — every override re-validated: color overrides must pass the
same contrast rules (else dropped + `LUMI0302` warning); families must exist in evidence.
- `NullRoleAssist`: returns None. Default everywhere; tests use it.
- `OpenRouterRoleAssist`: mirrors `image_provider.py`'s pattern — httpx POST chat completion,
  model from `LUMEN_INGESTION_ASSIST_MODEL` (default `anthropic/claude-sonnet-4.5`), api key
  `OPENROUTER_API_KEY`, strict JSON response (json_schema response_format; on parse failure →
  one retry, then None + LUMI0301). Enabled only when `LUMEN_INGESTION_ASSIST=1`. Narrative
  fields (description/tagline/values/tone) land in kit.description + constraints.tone +
  ingestion_report.narrative. **Do not call the network in tests.**

## 6. `jobs.py` + migration 007

Migration `007_ingestion_jobs.sql`:
```sql
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('website', 'pdf', 'asset_upload')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    request_json TEXT NOT NULL,
    evidence_json TEXT,
    brand_kit_id TEXT,
    brand_kit_version INTEGER,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status, created_at);
```
PLUS: rebuild `brand_kits` to extend the `source` CHECK with `'website', 'pdf',
'asset_upload'` (SQLite 12-step: create `brand_kits_new` with the same columns/PK and new
CHECK, `INSERT INTO ... SELECT`, drop old, rename; preserve `brand_compatibility_reports` FKs
— run inside the migration transaction; PRAGMA foreign_keys handling matches however
database.py runs migrations — READ database.py first and follow its conventions exactly).

`jobs.py`:
```python
class IngestionJobStore:                     # takes sqlite3.Connection like Repository
    def create(self, kind, request: dict) -> dict            # returns row dto, status=queued
    def get(self, job_id) -> dict | None
    def set_running(self, job_id) / set_stage(self, job_id, stage: str, progress: float)
    def complete(self, job_id, brand_kit_id, version, evidence_json: str | None)
    def fail(self, job_id, error: dict)

class StageReporter(Protocol):               # capture/normalize code takes this, not the store
    def __call__(self, stage: str, progress: float) -> None

def run_ingestion_job(store, job_id, work: Callable[[StageReporter], tuple[str, int, str | None]]) -> None
    # set_running → work(reporter) → complete; any exception → fail({code, message}) — never raises
```
Timestamps: ISO-8601 UTC via a `now_iso()` injectable (default `datetime.now(timezone.utc)`)
so tests can freeze it. `new_id("ingest")` pattern consistent with main.py's id helper.
Stage strings for slice 1 will be moda-style ("Visiting your website…") — jobs.py treats them
as opaque.

## 7. Requirements

`requirements.txt` additions (alphabetical, versioned like existing pins):
`fonttools>=4.53,<5`, `pillow>=10,<12`, `playwright>=1.45,<2`, `pymupdf>=1.24,<2`,
`pypdf>=4.2,<6`, `selectolax>=0.3.21,<1`, `tinycss2>=1.3,<2`.
Nothing in slice 0 imports them (verify with a test-time import check of lumen_ingestion).

## 8. Tests + fixtures (the DoD)

Fixtures in `apps/api/tests/fixtures/ingestion/`:
- `evidence_website_insight.json` — hand-authored BrandEvidence resembling the insighthealth
  scrape: mint/teal accents (#12EAB1, #00E3E1), ash black text (#1D1C1D), off-white page
  (#F5F5F5), soft indigo extra (#8080F9), Aeonik heading + body samples (h1 48/600, body 16/400),
  2 logo entries, 3 images, spacing/radius samples, a couple of rules, narrative. LIGHT ONLY
  (dark must be synthesized).
- `evidence_pdf_insight.json` — PDF-shaped: named colors with exact hex, pdf-heading/pdf-body
  type samples, fonts with faces=[] (files not sourced), clearspace + dont rules, dark-theme
  color evidence (theme="dark" from dark lockup pages).
- `evidence_minimal.json` — one color, nothing else (exercises every default/backfill path).
- `expected/` — golden kit snapshots for the three (stable ordering: sort all dict keys when
  dumping; the normalizer itself must produce deterministic output).

`test_ingestion_normalizer.py`:
1. Golden tests: normalize fixture → exact match against expected snapshot (json, sorted keys).
   Regenerate helper guarded by env `UPDATE_INGESTION_SNAPSHOTS=1`.
2. Required-token property: for each fixture AND a set of ~20 randomized evidence bundles
   (seeded `random.Random(0)`, vary counts/hex/weights/hints incl. empty), assert every
   required color/type/space/radius/stroke/opacity path present, every value parseable, every
   required color token has a `theme.dark` mode value, and each gap has a matching diagnostic.
3. Contrast property: text.primary vs surface.page ≥ 4.5 (both themes) on all bundles.
4. Determinism: normalize twice → identical JSON.
5. Engine round-trip (the real DoD): `CoreClient().validate_brand_kit(kit,
   product_ready=False)` returns ok for all three fixture kits; `summarize_brand_kit` succeeds;
   POST via TestClient `/brand-kits` (source `"api"` for now) persists and GET returns it.
   Mark these with the same pattern other core-hitting tests use (they run the cargo helper).
6. Dark synthesis marked: website fixture report says `dark_colorway: "synthesized"` +
   LUMI0210 present; PDF fixture (has dark evidence) says "captured".
7. Extras: soft indigo appears as `palette.extra.soft-indigo` with alias.

`test_ingestion_jobs.py`: create→running→stage→complete happy path; failure path stores
error_json and never raises; brand_kits source CHECK now accepts 'website' (insert a kit row
with source='website' via Repository.create_brand_kit); migration idempotence (fresh DB +
re-open existing DB per the restart test pattern in test_api.py:1926).

## 9. Verification

`cd apps/api && python -m pytest tests/test_ingestion_normalizer.py tests/test_ingestion_jobs.py -x -q`
then the full `python -m pytest tests -q` for regressions. Engine untouched in this slice —
no WASM rebuild needed.
