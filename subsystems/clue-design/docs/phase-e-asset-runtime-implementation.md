# Phase E: Asset Runtime And Creative Tools — Detailed Implementation Spec

Date: 2026-06-12
Branch: `phase-e/asset-runtime-v0`
Status: living implementation spec. Decisions 1-5 in
`docs/phase-e-asset-runtime-plan.md` are settled and restated here; this
document expands them into full architecture, contracts, slice specs,
diagnostics allocation, and test strategy.

Companion documents:

- `docs/phase-e-asset-runtime-plan.md` — the settled charter (decisions,
  slice list, gates). This spec does not re-litigate it.
- `design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md` —
  gap areas 11 (Assets And Imagery), 10 (Rendering/Export/Preview),
  1 (Source Of Truth); Phase E roadmap entry.
- `design/reference_docs/Brilliant-Reverse-Engineering-Report.md` —
  sections 11 (rendering/effects), 12 (agent/MCP tool surface, image
  tools, screenshot self-review loop).

## 1. Purpose

Phase E converts Lumen's fixture-only asset handling into a production
asset runtime. Today the Scene carries honest asset *metadata*
(`AssetRecord` with provenance, licensing, raster/vector/font/logo
metadata, digests, opaque locations) but no byte path: exports render
placeholder groups where images belong, the critic loop evaluates
documents whose imagery does not exist, and there is no way for a user or
agent to put a real logo into a real mailer.

The gap analysis is explicit about why this matters and where it sits in
sequence: asset runtime follows the quality loop (Phase A), layout/text
reliability (Phase B), brand maturity (Phase C), and targeted editing
(Phase D), and it is a hard prerequisite for Phase G, whose per-instance
artifacts (account logos, personalized QR codes on physical mailers) are
asset-generation problems. Two recorded demo failures are partially
recovered by this phase:

- "No Visual Repair After Success" — the critic previews evaluate real
  images/logos instead of placeholders, so visual critique stops being
  blind to roughly half the artifact.
- "Text And Elements Going Out Of Proportion" — fit, crop, aspect-ratio,
  and safe-area rules give the engine grounds to reject or warn about
  asset/text collisions instead of silently rendering them.

## 2. Target State After Phase E

When Phase E is complete, the following statements are true and covered
by tests:

1. **Real bytes flow end to end.** A PNG/JPEG/SVG uploaded through
   `POST /assets` is content-addressed (SHA-256) on disk, exactly once
   per digest; the same bytes appear as a data URI in SVG export, as
   decoded pixels in PNG export, in the editor canvas, and in the agent
   critic preview — all resolved through one trait, never stored in the
   Scene.
2. **Ingest is safe.** MIME type is sniffed from magic bytes and must be
   compatible with the declared type; size limits are enforced; SVG is
   sanitized (scripts, event handlers, foreignObject, script-bearing
   hrefs stripped) *before* bytes are stored; every record carries
   probed dimensions, DPI, transparency, and a thumbnail reference.
3. **Deterministic generation exists.** `generate_qr` produces a
   sanitized SVG asset from a URL/text with explicit error-correction
   level (M default, H for print), a 4-module quiet zone, and module
   metadata. The same input yields byte-identical SVG and therefore the
   same digest. Print-size diagnostics fire when the declared physical
   size falls below ~20mm at the declared DPI.
4. **Assets are a workspace library, not document captives.** Records
   can be listed, searched, filtered (kind, query, archived), and reused
   across documents; attaching to a document uses the existing canonical
   operations (`UpsertAsset`, `PlaceAssetInNode`, `PlaceAssetInSlot`)
   with envelope history via `/edits`.
5. **Lifecycle is archive-first with byte GC.** Archive is the default
   delete; hard delete is reference-checked at the record level (Phase D)
   and at the byte level (Phase E): bytes leave the store only when no
   record — library or in-document — still references their digest.
6. **Placement survives print.** Exporters honor contain/cover fit and
   focal-point crops; aspect-ratio mismatches, sub-threshold effective
   DPI for print, and logo safe-area violations surface as diagnostics in
   preflight/export, with precise subjects.
7. **Licensing is enforced at export, recorded at ingest.** Every upload
   and generation captures provenance and licensing; export rejects
   print/publish artifacts that embed assets whose license forbids it,
   with a diagnostic naming the asset and the restriction.
8. **The editor can do the workflow.** Upload, browse (with thumbnails),
   select, place, and replace — all emitting canonical operations.
9. **Generation is an adapter, not an architecture.** A provider trait
   normalizes any generator's output into an `AssetRecord` with
   provenance and licensing; QR is the first concrete provider; AI
   image/vectorization providers are stubs wired through the same trait
   so enabling a real model is configuration, not surgery.

## 3. What We Take From Brilliant (And What We Change)

The reverse-engineering report shows how Brilliant treats imagery as a
first-class agent capability. The mapping:

| Brilliant | Lumen Phase E |
|---|---|
| `generate_image` / `generate_images` (Nano Banana 2) | `AssetGenerationProvider` trait + stub AI provider (E8); real model is config later |
| `generate_svg` | Same trait, vector output kind; QR provider is the first deterministic vector generator (E4) |
| `vectorize_image` ("Source raster element left intact") | `AssetVectorizationProvider` trait + stub (E8); request/result contracts already exist in `lumen-core::assets` |
| Screenshot + self-review loop after each `<objects>` block | Critic preview consumes real bytes through the resolver (E1/E2 wiring + E9 conformance) so `get_latest_preview_for_critique` critiques real imagery |
| Direct canvas placement, aspect-ratio guidance | Canonical `PlaceAssetInNode`/`PlaceAssetInSlot` operations + placement semantics (fit/focal/aspect/DPI/safe-area) in E6 |
| Errors as partial application + fix hints, never crashes | Missing bytes/licensing problems degrade to diagnostics (LUME02xx/LUMA0xxx), never panics or silent placeholder success |
| Session-scoped refs so agents do not collide | Asset records are workspace-scoped rows with stable ids; agent tools record provenance in traces |

Deliberate differences:

- **Bytes never enter the document.** Brilliant can afford
  renderer-resident imagery; Lumen's Scene is the single source of truth
  shared by editor, exporter, API, and the future ABM runtime, so assets
  stay metadata + location ref, resolved adapter-side (Decision 3).
- **Determinism first.** Brilliant leads with AI generation; Lumen leads
  with QR codes because the ABM premise (per-account QR on physical
  mailers) demands deterministic, auditable artifacts and exercises the
  whole pipeline — generation, sanitization, storage, placement, print
  diagnostics — without an AI dependency (Decision 1).
- **Licensing is a contract, not a vibe.** Brilliant's binary shows no
  licensing enforcement; Lumen records license at ingest and enforces at
  export (Decision 5) because agency users redistribute physical print.

## 4. Settled Decisions (Restated)

1. QR codes are the first generation provider (`qrcode` crate, SVG out,
   EC M default / H print, 4-module quiet zone, <20mm print warning).
2. Storage is a trait with a local content-addressed adapter first
   (SHA-256 keys); S3-compatible adapter is a follow-up behind the same
   trait; bytes stored exactly once per digest.
3. Bytes never enter the Scene; `AssetRecord` stays metadata + location
   ref; resolution is adapter-side; lumen-core stays free of storage,
   HTTP, database, and browser knowledge.
4. Archive-first lifecycle (Phase D) extends to bytes: hard delete
   removes bytes only when no record references the digest.
5. Licensing enforced at export, recorded at ingest.

New architectural decisions made during implementation (recorded in
workstream memory as they land):

6. **A new crate `crates/lumen-assets` owns byte-touching asset logic**
   (storage trait + local adapter, MIME sniffing, probing, SVG
   sanitization, thumbnails, QR generation, provider traits). Rationale:
   lumen-core must stay dependency-light and wasm-clean (golden rule);
   lumen-export should not grow storage knowledge; the API helper should
   stay a thin action dispatcher. `lumen-assets` depends only on
   lumen-core (+ `sha2`, `image`, `qrcode`, `quick-xml`); it does not
   depend on lumen-export, and lumen-export does not depend on it. The
   API helper composes the two (store-backed resolver implementing
   `lumen_export::AssetByteResolver` over `lumen_assets::AssetStore`).
7. **The Python API reaches Rust through new helper actions**
   (`ingest_asset`, `generate_qr`, extended `export_preview`), keeping
   the action pattern from Phases C/D. Bytes cross the helper boundary
   base64-encoded; upload size limits keep this bounded.
8. **Store layout is `{root}/sha256/{first-two-hex}/{digest}`** and
   `AssetLocation { provider: "local-store", opaque_ref: <that relative
   path>, url: None }`. The API serves `GET /assets/{id}/bytes` by
   joining its configured root with `opaque_ref` — no second source of
   path truth.

## 5. Architecture

### 5.1 Topology and dependency rules

```
lumen-core        (Scene, AssetRecord, Operations, validation)  [wasm-clean]
   ^         ^                ^
   |         |                |
lumen-export lumen-assets   lumen-agent
 (resolver    (store, mime,
  trait, SVG/  probe, sanitize,
  PNG embed)   thumbs, QR, providers)
   ^                ^
   |                |
   +---- lumen-api-helper ----+   (composes: StoreBackedResolver,
                |                  ingest/generate actions)
                v
        apps/api (FastAPI)        (routes, persistence, byte serving)
           ^            ^
           |            |
   apps/editor    apps/agent_runtime
   (asset browser) (generate_qr / asset tools, critic preview)
```

Hard rules preserved:

- lumen-core: no storage, HTTP, DB, or browser APIs; no new heavyweight
  deps; compiles to wasm32-unknown-unknown.
- Asset bytes never serialize into the Scene; `AssetRecord` additions are
  metadata only (the single Phase E core change is an optional thumbnail
  reference on `AssetMediaMetadata`).
- All scene mutations remain canonical Operations; API writes persist
  edit envelopes through the existing `update_document_state` path.

### 5.2 Byte flow (upload)

1. Editor/agent → `POST /assets` (multipart: file + kind/label/license
   fields).
2. API reads bytes, enforces transport size limit, base64s into helper
   action `ingest_asset` with the configured `store_root`.
3. Helper (lumen-assets): sniff MIME from magic bytes → reject on
   mismatch with declared type; SVG → sanitize before anything else;
   probe (dimensions, DPI, transparency); derive thumbnail; write bytes
   (and thumbnail) content-addressed into the store (dedup by digest);
   assemble a full `AssetRecord` with media/digest/location/raster or
   vector metadata, provenance, license.
4. API persists the record as a workspace `assets` row and returns it
   with ingest diagnostics.

### 5.3 Byte flow (export/preview)

1. `POST /export-preview`, `/documents/{id}/export`, or agent
   `export_preview` → helper `export_preview` action now carrying
   `asset_store_root`.
2. Helper builds `LumenExportAdapter::with_resolver(StoreBackedResolver)`;
   the resolver reads `store_root.join(record.media.location.opaque_ref)`
   for `provider == "local-store"`, falls back to digest lookup, and
   returns `ResolvedAssetBytes`.
3. SVG embeds data URIs; PNG rasterizes them (resvg); failures degrade to
   placeholder markup + LUME0210/LUME0211 diagnostics; missing resolver
   keeps LUME0202 (back-compat).

### 5.4 Byte flow (generation)

1. Agent tool / API route / editor → `generate_qr` (helper action or
   `POST /assets/generate/qr`).
2. lumen-assets builds the QR matrix (qrcode crate), renders
   deterministic SVG (own serializer: fixed attribute order, fixed number
   formatting, single path for dark modules, explicit 4-module quiet
   zone), sanitizes (defense in depth), stores via the same ingest path,
   returns record + module/EC metadata + print-size diagnostics.
3. Placement onto the document goes through `UpsertAsset` +
   `PlaceAssetInNode`/`PlaceAssetInSlot` (optionally via `/edits`).

## 6. Contracts

### 6.1 `AssetByteResolver` (lumen-export, shipped in E1)

```rust
pub struct ResolvedAssetBytes { pub mime_type: String, pub bytes: Vec<u8> }
pub struct AssetResolveError { pub code: &'static str, pub message: String }

pub trait AssetByteResolver: Debug + Send + Sync {
    fn resolve(&self, asset: &AssetRecord)
        -> Result<ResolvedAssetBytes, AssetResolveError>;
}
```

Implementations: `FixtureAssetResolver` (in-memory, asset-id keyed with
digest fallback; preserves deterministic tests per the gap analysis
"preserve fixture assets" guidance) and `StoreBackedResolver`
(api-helper, over `AssetStore`). Adapters: `SvgExportAdapter`,
`PngExportAdapter`, `LumenExportAdapter::with_resolver`. PDF embedding is
deferred (print preflight already validates asset metadata); the PDF
exporter keeps metadata-driven diagnostics.

### 6.2 `AssetStore` (lumen-assets, E2)

```rust
pub struct StoredObject {
    pub digest_value: String,      // sha256 hex
    pub byte_length: u64,
    pub relative_path: String,     // "sha256/ab/abcd..."
    pub deduplicated: bool,        // bytes already existed
}

pub trait AssetStore: Debug + Send + Sync {
    fn put(&self, bytes: &[u8]) -> Result<StoredObject, AssetStoreError>;
    fn get(&self, relative_path: &str) -> Result<Vec<u8>, AssetStoreError>;
    fn contains_digest(&self, digest_value: &str) -> bool;
    fn delete_digest(&self, digest_value: &str) -> Result<bool, AssetStoreError>;
}
```

`LocalAssetStore { root }` is the first adapter. Writes are
atomic-by-rename (temp file then rename) so a crashed ingest never leaves
a half-written digest path. An S3-compatible adapter is a follow-up
behind the same trait (non-goal here).

### 6.3 Ingest pipeline (lumen-assets, E2/E3)

```rust
pub struct IngestRequest<'a> {
    pub bytes: &'a [u8],
    pub declared_mime: Option<&'a str>,
    pub filename: Option<&'a str>,
    pub kind_hint: Option<AssetKind>,
    pub max_bytes: u64,
}
pub struct IngestOutput {
    pub bytes: Vec<u8>,            // possibly sanitized (SVG)
    pub sniffed_mime: String,
    pub kind: AssetKind,
    pub raster: Option<RasterAssetMetadata>,
    pub vector: Option<VectorAssetMetadata>,
    pub thumbnail: Option<ThumbnailOutput>,
    pub diagnostics: Vec<Diagnostic>,
}
```

Supported MIME sniffs: PNG, JPEG, GIF, WebP, SVG (text head heuristic:
optional BOM/whitespace/XML declaration + `<svg`), PDF (kind Document, no
probe). Anything else: `AssetKind::Other` with a warning, or rejection
when a declared type contradicts the sniff.

SVG sanitization (quick-xml event rewrite): drop `script` and
`foreignObject` subtrees; drop every `on*` attribute; drop
`href`/`xlink:href` whose value scheme is `javascript:` (case/space
tolerant); record each removal in a diagnostic note. Sanitization runs
before storage so hostile bytes never persist (target-state statement 2).

Probing: dimensions + alpha via the `image` crate; DPI via direct chunk
parsing (PNG `pHYs`, JPEG JFIF density) because the `image` crate does
not expose density; SVG width/height/viewBox parsed during sanitization.
Thumbnails: rasters resized to fit 256px and re-encoded PNG, stored
content-addressed like any bytes; SVG uses the sanitized vector itself as
its thumbnail (scales for free); the record carries
`media.thumbnail: Option<AssetThumbnail { location, mime_type }>`
(serde-defaulted; pre-E3 JSON parses unchanged).

### 6.4 QR provider (lumen-assets, E4)

```rust
pub struct QrRequest {
    pub data: String,
    pub ec_level: QrEcLevel,          // L/M/Q/H; default M, H for print
    pub target_width_mm: Option<f64>, // for print-size diagnostics
    pub print: bool,
}
pub struct QrOutput {
    pub svg: String,                  // deterministic bytes
    pub module_count: u32,            // width incl. data modules
    pub quiet_zone_modules: u32,      // always 4
    pub ec_level: QrEcLevel,
    pub diagnostics: Vec<Diagnostic>,
}
```

Determinism contract: the SVG serializer is owned by Lumen (not the
qrcode crate's renderer) — fixed header, fixed viewBox arithmetic, one
`<path>` of `M x y h1v1h-1z` cells in row-major order — so byte equality
holds across runs and stays stable under dependency upgrades unless the
QR spec output itself changes (covered by a pinned-digest test).

### 6.5 Generation provider contracts (E8)

`lumen-core` already defines the data contracts
(`AssetGenerationRequest/Result`, `AssetVectorizationRequest/Result`).
lumen-assets adds the behavior traits:

```rust
pub trait AssetGenerationProvider: Debug + Send + Sync {
    fn id(&self) -> &'static str;          // "qr-v1", "stub-image-v0"
    fn generate(&self, request: &AssetGenerationRequest)
        -> Result<ProviderArtifact, ProviderError>;
}
pub trait AssetVectorizationProvider: Debug + Send + Sync { /* same shape */ }

pub struct ProviderArtifact {
    pub bytes: Vec<u8>,
    pub mime_type: String,
    pub kind: AssetKind,
    pub license: AssetLicense,
    pub provenance_notes: Vec<String>,
    pub provider_metadata: BTreeMap<String, String>,
}
```

Normalization is shared: every provider artifact runs through the same
ingest pipeline (sanitize/probe/thumbnail/store) and lands as an
`AssetRecord` with `source: Generated { request_id, model: provider_id }`
and `provenance.source_label: "generated:<provider>"`. QR adapts onto
this trait; the AI image and vectorization providers ship as
deterministic stubs proving the contract (real providers are config, not
architecture).

### 6.6 Persistence (apps/api, E2/E5)

Migration `004_assets.sql`:

```sql
CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,            -- pending|ready|failed|archived
  mime_type TEXT,
  digest_algorithm TEXT,
  digest_value TEXT,
  byte_length INTEGER,
  filename TEXT,
  tags_json TEXT NOT NULL,
  record_json TEXT NOT NULL,       -- the full AssetRecord
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_digest ON assets(digest_value);
CREATE INDEX IF NOT EXISTS idx_assets_kind_status ON assets(kind, status);
```

The row is a projection; `record_json` is canonical and round-trips the
Rust `AssetRecord`. The legacy `asset_metadata` table/routes remain
untouched for backward compatibility.

Routes:

- `POST /assets` — multipart upload → ingest → row; returns record +
  diagnostics + `deduplicated`.
- `GET /assets` — `kind=`, `q=` (label/filename/tags), `include_archived=`
  (default false), `limit/offset`.
- `GET /assets/{id}` — record.
- `GET /assets/{id}/bytes` — streamed bytes with sniffed MIME.
- `GET /assets/{id}/thumbnail` — thumbnail bytes (falls back to bytes for
  SVG).
- `POST /assets/{id}/archive`, `POST /assets/{id}/restore`.
- `DELETE /assets/{id}` — hard delete; refuses while any document scene
  or other library row references the record/digest; deletes bytes only
  when the digest reference count reaches zero (Decision 4).
- `POST /assets/generate/qr` — QR generation (E4).

Configuration: `LUMEN_ASSET_STORE_ROOT` (default: alongside the SQLite
file, `<data-dir>/asset-store`); `LUMEN_ASSET_MAX_BYTES` (default 10 MiB).

### 6.7 Diagnostics allocation

Shipped in E1:

- `LUME0210` (warning, export): resolver failed to produce bytes.
- `LUME0211` (warning, export): image node's asset record missing from
  the scene.

Allocated for the remaining slices:

- `LUMA0600` (error, ingest): sniffed MIME contradicts declared type.
- `LUMA0601` (error, ingest): byte length exceeds the configured limit.
- `LUMA0602` (warning, ingest): unsupported/unknown MIME ingested as
  `Other`.
- `LUMA0603` (warning, ingest): SVG sanitization removed constructs
  (lists what was stripped).
- `LUMA0604` (warning, ingest): probe failed; record stored without
  raster/vector metadata.
- `LUMA0605` (warning, ingest): thumbnail derivation failed.
- `LUMA0700` (warning, generation): QR below ~20mm at declared print
  size.
- `LUMA0701` (error, generation): QR data exceeds capacity at the
  requested EC level.
- `LUMA0702` (error, generation): empty/blank QR data.
- `LUME0212` (error, export): asset license forbids export for this
  profile/purpose (licensing rejection; preflight + export).
- `LUME0220` (warning, export): effective DPI below print threshold for
  the rendered size.
- `LUME0221` (warning, export): logo clearspace/safe-area violation.

### 6.8 Agent tool surface (E4/E9)

`apps/agent_runtime/lumen_deepagent/tools.py` gains:

- `generate_qr(data, ec_level=None, print_media=False, target_width_mm=None, label=None)`
  → helper `generate_qr`; upserts the returned record into the scene via
  canonical `UpsertAsset`; trace event records provider id, EC level,
  module count, digest, and provenance (mirrors Brilliant's
  generate-then-place tools, with audit).
- Critic preview (`export_preview*`, `get_latest_preview_for_critique`)
  rides the resolver-wired helper automatically once `asset_store_root`
  flows through (E2): no tool-signature change, previews simply stop
  being blind.

## 7. Slice Specs

Working discipline: one commit per slice; every slice lands with
`cargo fmt && cargo clippy --all-targets -- -D warnings && cargo test &&
cargo check --target wasm32-unknown-unknown -p lumen-core`, plus API and
agent pytest when Python changes, plus editor lint/test/build when the
editor changes. Memory entries follow each slice.

### E1. Asset byte resolver (shipped, commit `8097603`)

Scope: `AssetByteResolver`/`ResolvedAssetBytes`/`AssetResolveError` +
`FixtureAssetResolver` in `lumen-export/src/resolver.rs`; SVG `<image>`
data-URI embedding with fit→preserveAspectRatio mapping; PNG
rasterization through the shared renderer; diagnostics LUME0210/0211;
LUME0202 retained when no resolver is configured.
Tests (7, `lumen-export/tests/asset_resolution.rs`): data-URI embed,
no-resolver warning, missing-bytes diagnostic-not-panic, missing-record
diagnostic, digest fallback, raster pixel assertion, critic-path gate.

### E2. Storage + upload API

Rust: `crates/lumen-assets` (store.rs, mime.rs); `StoreBackedResolver` +
`ingest_asset` action + `export_preview.asset_store_root` in the helper.
Python: migration 004, `POST /assets`, `GET /assets/{id}/bytes`, store
root config, `python-multipart` dependency.
Tests: Rust — put/get/dedup/delete, atomic write, sniffing table,
declared-vs-sniffed mismatch; helper CLI ingest round-trip. Python —
upload creates digest-keyed file; duplicate upload dedups (one file, two
records OK); MIME mismatch → 400 with LUMA0600; size limit → 413;
round-trip gate: upload → place via operations → export contains data URI.

### E3. Processing

Rust (lumen-assets): probe.rs (image crate + PNG pHYs/JPEG JFIF density
parsing), sanitize.rs (quick-xml rewrite), thumbs.rs; ingest pipeline
composes them; lumen-core gains `AssetMediaMetadata.thumbnail`
(serde-defaulted, metadata-only).
Tests: probe fills width/height/dpi/alpha for the 300-dpi fixture PNG;
hostile SVG (script, onload, foreignObject, javascript: href) comes out
clean with LUMA0603 notes; idempotent sanitization; thumbnail ≤256px and
stored; API exposes `GET /assets/{id}/thumbnail`.

### E4. QR provider

Rust (lumen-assets): qr.rs per contract 6.4; helper `generate_qr` action
storing through the ingest pipeline.
Python: `POST /assets/generate/qr`; agent tool `generate_qr` with traced
provenance.
Tests: byte determinism (two runs, equal bytes, pinned digest); EC level
changes bytes; quiet zone arithmetic (viewBox = modules + 8); capacity
error; print-size diagnostic below 20mm; API route persists record with
`source.kind == "generated"`; agent trace carries provider metadata.
Gate: a mailer fixture carries a QR; scannability evidence recorded in
memory (decode check if a decoder is available, otherwise structural
verification recorded honestly).

### E5. Asset library API

Python: `GET /assets` list/search/filter; archive/restore; hard delete
with record- and byte-level reference checks (scene JSON digest scan +
library rows); reuse across documents documented as
`UpsertAsset`/`PlaceAsset*` (no new mutation surface).
Tests: filter matrix (kind/q/archived default-exclusion); archive then
default-list excludes; restore re-includes; hard delete refuses while
referenced; digest GC removes bytes only at refcount zero; cross-document
reuse keeps one byte copy.

### E6. Placement semantics

Rust: exporters honor `AssetPlacement.fit` (contain/cover already
mapped) plus focal-point crop windows (computed from natural dimensions
in record metadata, rendered as nested viewBox/clip); export preflight
adds LUME0212 licensing rejection, LUME0220 effective-DPI-for-print, and
LUME0221 logo clearspace checks; aspect-ratio validation stays in
lumen-core validation (LUMA0310) and is exercised end-to-end.
Tests: golden SVGs for contain/cover/focal-crop; low-DPI print warning
fires for a small image stretched large at print DPI; logo safe-area
warning; licensing rejection blocks a print export and names the asset.

### E7. Editor asset browser

TypeScript: `AssetBrowserPanel` (list + thumbnails + upload + search),
placement actions emitting canonical `UpsertAsset` +
`PlaceAssetInNode`/`PlaceAssetInSlot` (via `/edits` when a documentId is
present, matching HistoryPanel's pattern); replace re-emits placement on
the selected node.
Tests (Vitest): panel fetch/render with mocked API; upload posts
multipart; placing emits the canonical operation sequence; replace
preserves node identity.

### E8. Generation/vectorization adapter contracts

Rust (lumen-assets): traits per contract 6.5; QR adapted as the first
concrete provider; `StubImageProvider` (deterministic placeholder PNG)
and `StubVectorizationProvider` (deterministic path extraction stub)
prove the seam; helper `generate_asset` action normalizing any provider
through ingest.
Tests: provider round-trip via the trait object; provenance/licensing
present on every generated record; stub determinism; unknown provider id
is a typed error.

### E9. Conformance

Cross-cutting fixtures and the full matrix: export-with-real-bytes vs
fixture baseline; licensing rejection scenario; QR determinism replay;
archive→hard-delete byte lifecycle scenario; agent runtime test proving
the critic preview consumes real assets (no LUME0202/0210/0211 in the
preview diagnostics for a resolvable scene). Full command matrix from
section 8 runs green; memory records final status.

## 8. Test Matrix

- `cargo fmt --check`
- `cargo clippy --all-targets -- -D warnings`
- `cargo test` (workspace, includes `-p lumen-assets`, and
  `-p lumen-export --test asset_resolution`)
- `cargo check --target wasm32-unknown-unknown -p lumen-core`
- `.venv/bin/python -m pytest apps/api/tests apps/agent_runtime/tests -q`
- `npm --prefix apps/editor test -- --run`
- `npm --prefix apps/editor run lint && npm --prefix apps/editor run build`

## 9. Non-Goals (Unchanged)

AI image-generation model integration beyond the adapter contract;
background removal/image editing; font asset runtime; CDN/signed-URL/S3
serving; per-instance binding of generated assets (Phase G consumes the
generators E provides).

## 10. Risks And Fallbacks

- **resvg data-URI support regresses** → pixel-assertion test catches it;
  fallback is `xlink:href` + namespace declaration (verified working in
  resvg 0.45).
- **DPI metadata absent in uploads** → record stores `None`; print
  preflight downgrades to the existing LUMA0312 "requires DPI metadata"
  warning rather than guessing.
- **quick-xml sanitization edge cases** (nested CDATA, entity tricks) →
  sanitizer is allowlist-shaped (drop unknown event types in script
  context), idempotent, and fuzz-style tested with hostile fixtures;
  worst case the SVG is rejected, never stored unsanitized.
- **Base64-over-helper overhead** → bounded by `LUMEN_ASSET_MAX_BYTES`;
  if profiling ever shows pain, the helper can accept a temp-file path —
  contract change is internal to API↔helper.
- **Scene-JSON digest scan for byte GC is coarse** → conservative in the
  safe direction (false positives keep bytes); a reference-count table is
  a cheap later optimization.
- **Slice overrun** → implement the conservative core, record the cut in
  workstream memory (standing instruction).

## 11. Downstream Implications

- **Phase F (editor/export productization)** consumes the asset browser,
  thumbnails, and placement controls; PDF byte embedding lands there or
  in an export-fidelity follow-up using the same resolver.
- **Phase G (ABM runtime)** calls the E8 provider seam per instance
  (account logo selection, per-account QR), binds results through the
  same canonical operations, and relies on E5 library scoping and E6
  print diagnostics for batch validation.
- **Brand kit ingestion** (gap area 9) gets its missing primitive: brand
  logo/font assets can now be real uploaded bytes with provenance.

## 12. Final Status (2026-06-12)

All nine slices are implemented and green on the full matrix.

| Slice | Commit | Delivered |
|---|---|---|
| E1 | `8097603` | Byte resolver trait, fixture resolver, real-byte SVG/PNG embedding, LUME0210/0211 |
| E2 | `5e32284` | lumen-assets crate: content-addressed store, MIME sniffing, ingest; helper ingest_asset + store-backed resolver; POST /assets, byte serving |
| E3 | `b73bde8` | Probing (dims/DPI/alpha), SVG sanitization, thumbnails, AssetThumbnail metadata, thumbnail route |
| E4 | `5ee8a0c` | Deterministic QR provider (pinned digest), helper/API/agent surfaces, zxing-cpp scan check |
| E5 | `1ff5cda` | Asset library list/search/filter, archive/restore, reference-checked hard delete with digest-level byte GC |
| E6 | `64b7255` | Focal-point crops, contain/cover mapping, LUME0212 licensing enforcement, LUME0220 print DPI, LUME0221 logo safe area |
| E7 | `6e5e284` | Editor asset browser + library client emitting canonical operations |
| E8 | `e57ce8c` | Generation/vectorization provider traits, registry, QR adapter, stub providers, helper generate_asset |
| E9 | (this commit) | Conformance fixture (placeholder baseline vs real bytes), end-to-end licensing rejection, critic store-root wiring test |

Verification (final run): `cargo fmt --check`; `cargo clippy
--all-targets -- -D warnings`; `cargo test` (324 passed);
`cargo check --target wasm32-unknown-unknown -p lumen-core`;
`pytest apps/api/tests apps/agent_runtime/tests` (88 passed, 1
skipped); `npm --prefix apps/editor test -- --run` (182 passed, 19
files); editor lint + build; `git diff --check`.

Recorded scope cuts (workstream memory has details): PDF byte
embedding rides the export-fidelity follow-up (print preflight remains
metadata-driven); `generate_asset` has helper + tests but no public
API route or agent tool yet (Phase G consumes the seam); SVG assets
serve their own bytes as thumbnails; the editor panel places into
nodes (slot placement builder shipped and tested, SlotInspector
integration is Phase F polish).
