# Slice 1 design — web-scrape path (tiered capture + ingest routes)

Implementation spec for Brand-kit Ingestion v1 slice 1 (plan §6.0/§6.3/§7; slice 0 shipped
`444ec7c` — read SLICE0-DESIGN.md first; this spec builds strictly on it). **Hard requirement
from the user: all fetch fan-out is async (httpx.AsyncClient) with bounded concurrency — no
serial download loops.**

## 0. Module layout

```
apps/api/lumen_ingestion/
  capture/
    __init__.py          # capture_website() entry, CaptureOutcome
    snapshot.py          # SiteSnapshot model + record/replay (json, bytes base64)
    static.py            # Tier-1: async fetch + follow CSS imports/links
    parse.py             # SiteSnapshot -> raw evidence pieces (CSS/DOM analysis)
    quality_gate.py      # evidence-quality score + escalation decision
    rendered.py          # Tier-2: Playwright (async API, lazy import)
    evidence_builder.py  # SiteSnapshot(+parse) -> BrandEvidence (ingests assets)
    net.py               # SSRF guard, size/timeout caps, bounded fetch helpers
  pipeline.py            # run_website_ingestion(): job glue (capture→evidence→normalize→persist)
apps/api/lumen_api/models.py   # + IngestWebsiteRequest
apps/api/lumen_api/dto.py      # + ingestion_job_dto
apps/api/lumen_api/main.py     # + 2 routes
apps/api/tests/test_ingestion_capture.py
apps/api/tests/test_ingestion_routes.py
apps/api/tests/fixtures/ingestion/snapshots/   # recorded SiteSnapshot bundles
```

Ownership split (two agents): **Agent A** owns `capture/` + test_ingestion_capture.py +
snapshot fixtures. **Agent B** owns pipeline.py + models/dto/main.py routes +
test_ingestion_routes.py. The contract between them is §1 + §5 signatures — neither touches
the other's files.

## 1. Contracts (shared — implement exactly)

```python
# capture/__init__.py
@dataclass
class CaptureOutcome:
    snapshot: SiteSnapshot            # replayable raw capture
    tier: Literal["static", "rendered"]
    escalated: bool                   # gate fired
    escalation_reason: str | None
    diagnostics: list[dict]           # LUMI05xx capture diagnostics

async def capture_website(
    url: str,
    *,
    reporter: Callable[[str, float], None],   # StageReporter from slice 0
    force_render: bool = False,
    render_available: bool | None = None,     # None = autodetect playwright import
    http_client: httpx.AsyncClient | None = None,   # injectable for tests
) -> CaptureOutcome

# capture/evidence_builder.py  (sync wrapper; internally async for asset ingest)
def build_evidence(
    outcome: CaptureOutcome,
    *,
    core: CoreClient,
    store_root: str,
    reporter: Callable[[str, float], None],
) -> BrandEvidence

# pipeline.py (Agent B)
def run_website_ingestion(
    database_path: str | Path,
    asset_store_root: str,
    job_id: str,
    *,
    capture=capture_website,          # injectable for tests
) -> None                             # never raises (uses run_ingestion_job)
```

## 2. `net.py` — fetch discipline (Agent A)

- `guard_url(url) -> str`: require http/https; resolve DNS (`socket.getaddrinfo` in
  `asyncio.to_thread`) and reject loopback/private/link-local/multicast/reserved ranges
  (`ipaddress` module) for EVERY resolved address; reject userinfo in netloc, non-standard
  ports other than 80/443/8080. Raise `CaptureError(code="LUMI0501", message=...)`. Re-guard
  after redirects (fetch with `follow_redirects=False` loop, max 5 hops, guarding each hop).
- `BoundedFetcher`: wraps `httpx.AsyncClient`; per-request timeout 15s, response size caps
  (page/CSS 5 MB, font 10 MB, image 15 MB — stream + abort over cap → per-item diagnostic
  `LUMI0502`, item skipped), browser-ish UA + `Accept-Language: en`, and a
  `asyncio.Semaphore(8)` shared across the capture. Concurrency is the point: expose
  `fetch_many(requests) -> list[Result]` built on `asyncio.gather(return_exceptions=True)`;
  individual failures never fail the batch (diagnostic per failure `LUMI0503`).
- All bytes fetched at most once per URL (dedupe map keyed on absolute URL).

## 3. `snapshot.py` — the replayable bundle (Agent A)

```python
class SiteSnapshot(BaseModel):
    schema_version: int = 1
    requested_url: str
    final_url: str
    fetched_at: str                   # ISO, caller-supplied
    tier: Literal["static", "rendered"]
    html: str                         # capped 2 MB (truncate + diagnostic)
    stylesheets: list[{url: str, text: str}]        # inline <style> gets url "inline:<n>"
    custom_props: dict[str, str] | None = None      # rendered tier: getComputedStyle(:root)
    computed_samples: list[dict] | None = None      # rendered tier only (§6 shape)
    downloads: list[{url: str, kind: "font"|"image"|"logo"|"screenshot",
                     content_type: str | None, bytes_b64: str, sha256: str}]
    meta: dict                        # title, meta description, og:*, favicon/apple-touch hrefs
save_snapshot(snapshot, path) / load_snapshot(path)
```
Snapshots are the golden-fixture format: tests replay them through parse → evidence →
normalize with zero network. Keep fixture snapshots SMALL (tiny hand-made woff/png/svg bytes).

## 4. `static.py` — Tier 1 (Agent A)

`async fetch_static(url, fetcher, reporter) -> SiteSnapshot`:
1. reporter("Visiting your website…", 0.05): fetch page HTML (redirect loop with re-guard).
2. reporter("Reading your styles…", 0.15): parse DOM (selectolax): collect `<link
   rel=stylesheet>` hrefs + `<style>` bodies. **Fetch ALL external stylesheets
   concurrently** (fetch_many). Then scan fetched CSS for `@import` (one level deep) →
   fetch those concurrently too.
3. reporter("Collecting your logos…", 0.30) + reporter("Gathering your visuals…", 0.45):
   identify candidates (§5 heuristics) and **download all fonts + logos + images in ONE
   concurrent batch** (fetch_many; kinds tagged per item).
4. Assemble SiteSnapshot(tier="static").
Everything network-bound overlaps; the only serial dependency is page → (css, asset lists).

## 5. `parse.py` — CSS/DOM analysis (Agent A; pure, works on any SiteSnapshot)

Output: `ParsedSite` (internal dataclass) with lists mirroring BrandEvidence fields but
pre-asset-ingest (colors/type_samples/fonts have source URLs, logos/images reference download
sha256s). Rules:

- **CSS iteration** (tinycss2): for each stylesheet, walk qualified rules + at-rules.
  Track `@media (prefers-color-scheme: dark)` scope → colors found inside get
  `theme="dark"`. Parse declarations: `color`, `background(-color)`, `border(-color)`,
  `fill` → ColorEvidence; `font-family/size/weight/line-height/letter-spacing` → type info.
  Color value parsing: hex (3/4/6/8), rgb[a](), hsl[a]() → hex; `var(--x)` resolved against
  collected custom props (one hop); skip `transparent/inherit/currentColor/unset`.
- **Custom props**: `:root`/`html` rule blocks → `custom_props`; each color-valued prop →
  ColorEvidence with hint `custom-prop:<name>`, weight 3.0.
- **Selector role hints** (match on any compound selector containing the token):
  `body/html` → page-bg (bg) / body-text (color), weight 5.0; `h1-h3` → heading-text;
  `p/li` → body-text; `a` → link; `button/.btn/.button/[class*=cta]` → button-bg (bg) /
  button-text (color), weight 4.0; `nav/header/footer` → weight 2.0 unhinted. Other
  selectors: weight 0.5, no hints. Aggregate duplicate values by summing weights (the
  normalizer clusters anyway).
- **Type samples**: from the same selector classes (label = h1…h6/body/button/nav).
  font-size only when px/rem/em (rem/em × 16); skip vw/clamp() (record none). font-family:
  first non-generic family, strip quotes.
- **@font-face**: family, weight (default 400), style, src url() candidates — prefer woff2 >
  woff > ttf/otf; absolute-ize URLs. license_hint "trial-filename" when filename matches
  /trial/i; "google-fonts" when host is fonts.gstatic.com.
- **Logo heuristics** (DOM): `<img>`/`<svg>` inside `header/nav/[class*=logo]/a[href="/"]`
  (svg inline → serialize markup as an SVG download entry); `link rel="apple-touch-icon"`,
  `meta property="og:logo"`; og:image is an IMAGE (kind og_image) not a logo. usage_hint:
  "primary" for header img/svg, "mark" for apple-touch-icon. background_hint: nearest
  ancestor bg color when resolvable from CSS (best effort, else None).
- **Images**: `<img src>` with rendered-size hints (width/height attrs) or natural file
  size ≥ 10 KB; cap 12 images by (attr area, then file size) — cap + skip count →
  diagnostic `LUMI0504`. Skip data: URIs > 50 KB, tracking pixels (≤ 4px).
- **Narrative**: `<title>`, meta description, og:site_name/og:title/og:description;
  visible text: first ~3000 chars of body text (selectolax .text(), whitespace-collapsed) →
  `text_excerpt`; brand_name = og:site_name else title before `|`/`—`; url = final_url.
- Every ColorEvidence/TypeSample pointer: `EvidencePointer(source="website",
  locator=f"{stylesheet_url} :: {selector}")` (or `"dom :: <where>"` for DOM finds).

## 6. `rendered.py` — Tier 2 (Agent A)

`async fetch_rendered(url, fetcher, reporter) -> SiteSnapshot` — lazy `from playwright.async_api
import async_playwright` inside the function. chromium headless; viewport 1440×2000;
`wait_until="networkidle"` (timeout 30s, fall through on timeout with diagnostic); auto-scroll
to bottom in steps (max 10 × 800px, 200ms pauses) for lazy content. One `page.evaluate` returns:
- computed samples: for body, h1-h6, p (first 3 each), a (first 5), button/.btn (first 5),
  nav, header, footer, and the 40 largest visible elements: `{selectorish, tag, bg, color,
  fontFamily, fontSize, fontWeight, lineHeight, letterSpacing, borderRadius, area}` (area =
  getBoundingClientRect w×h, viewport-clipped; bg only when non-transparent).
- `getComputedStyle(document.documentElement)` custom props (`--*`).
- All stylesheet hrefs + inline css texts (document.styleSheets; cssRules may throw cross-
  origin → collect href only, fetch via fetcher afterward).
`page.screenshot(full_page=True)` → downloads entry kind "screenshot". Then reuse static's
asset identification on the rendered DOM (`page.content()`) + concurrent downloads via
fetcher. Snapshot: tier="rendered", computed_samples + custom_props set.
parse.py consumes computed_samples when present: each sample → ColorEvidence with weight
`log2(1+area)/4` (min 0.5) and the same hint mapping (body → page-bg/body-text etc.);
custom props → hinted evidence exactly like Tier 1.
**No playwright in unit tests** — rendered.py is exercised by the live e2e only; its parse
integration is tested by a hand-authored rendered-tier snapshot fixture.

## 7. `quality_gate.py` (Agent A)

`evaluate(snapshot, parsed) -> GateResult{score: float, escalate: bool, reasons: [str]}`.
Escalate (tier static only) when ANY of: visible text < 400 chars AND html < 20 KB
(client-rendered shell); distinct color evidence < 4; no type sample with a family; zero
stylesheets fetched. Diagnostic `LUMI0505` info with reasons when escalating;
`LUMI0506` warning when escalation needed but `render_available=False` (proceed with what we
have — graceful degradation per plan §6.3.5). `capture_website` wires: static → gate →
maybe rendered (reporter("Taking a closer look…", 0.55)); `force_render=True` skips straight
to rendered.

## 8. `evidence_builder.py` (Agent A)

`build_evidence(outcome, *, core, store_root, reporter)`:
- reporter("Capturing your colors…", 0.65) / ("Matching your typography…", 0.75) while
  mapping ParsedSite → BrandEvidence (§5 already produced the pieces; this step finalizes).
- Asset ingestion: fonts/logos/images/screenshot downloads → `core.ingest_asset(...)`
  (kind: "font"|"image"; label from filename; tags ["brand-ingestion", kind]; provenance
  {"kind":"url","url":...} — mirror existing ingest_asset callers in main.py for exact
  field conventions). ingest_asset is a blocking subprocess → run via
  `asyncio.to_thread` with `Semaphore(4)`, all assets concurrent (`asyncio.gather`) inside
  `asyncio.run` (build_evidence itself is sync — it owns the event loop).
  asset_id: `f"asset_ing_{sha256[:16]}"` (content-addressed → idempotent re-ingest; on
  "already exists"-class CoreError, reuse the id — read main.py's ingest error handling).
- Font faces get asset_id when their file downloaded; else source_url only.
- Images: transparency/dominant_colors left empty in slice 1 (Pillow analysis is slice 3);
  width/height from attrs when known.
- evidence.source = `{"kind":"website","url":requested_url,"captured_at":fetched_at,
  "confidence":0.7}`; screenshots list = screenshot asset ids.

## 9. `pipeline.py` + routes (Agent B)

`run_website_ingestion(database_path, asset_store_root, job_id, *, capture=capture_website)`:
sync function safe for FastAPI BackgroundTasks: open own sqlite connection
(`database.connect`), `IngestionJobStore`, then `run_ingestion_job(store, job_id, work)`.
`work(reporter)`:
1. Load job row → request (url, name, brand_kit_id).
2. `outcome = asyncio.run(capture(url, reporter=reporter, ...))`.
3. `evidence = build_evidence(outcome, core=CoreClient(), store_root=..., reporter=reporter)`.
4. reporter("Preparing your brand kit…", 0.85): `normalize_evidence(evidence,
   brand_kit_id=req or f"brand_kit_ing_{job_id_suffix}", name=req.name or narrative
   brand_name or host, created_at=<job created_at date>, version=1)`.
5. Persist mirroring main.py's create_brand_kit flow: core.validate_brand_kit(kit,
   product_ready=False) → summarize_brand_kit → merge `summary["ingestion"] =
   result.ingestion_report` → `Repository.create_brand_kit(kit, summary,
   diagnostics(normalizer + capture + validation), source="website")`.
6. Store evidence_json on the job (BrandEvidence dump, EXCLUDING any bytes — it has none).
7. Return (brand_kit_id, version, evidence_json) per run_ingestion_job's contract.

Routes (main.py, patterns identical to neighbors):
- `POST /brand-kits/ingest/website` — `IngestWebsiteRequest{url: str, name: str | None = None,
  brand_kit_id: str | None = None, force_render: bool = False}`. Validate + SSRF-guard the
  URL **synchronously in the route** (guard_url in a thread via `anyio.to_thread.run_sync`
  or just call it — route may be `async def`; follow existing main.py style which is sync
  `def` → call guard directly, it's fast) → 422 on rejection. Create job (kind "website",
  request_json = payload dump) → `background_tasks.add_task(run_website_ingestion,
  app.state.database_path, asset_store_root(), job["job_id"])` → return
  `{schema_version: 1, "job": ingestion_job_dto(job)}`.
- `GET /brand-kits/ingest/{job_id}` — job dto: `{job_id, kind, status, stage, progress,
  brand_kit_id, brand_kit_version, error, created_at, updated_at}` (no request/evidence
  bodies; 404 via existing not-found pattern).
Note route ordering: register BEFORE `GET /brand-kits/{brand_kit_id}` so "ingest" isn't
captured as a kit id (FastAPI matches in registration order — verify placement).

## 10. Tests

Agent A — `test_ingestion_capture.py` (no network, no playwright):
- Snapshot fixtures: `snapshots/insight_static.json` — hand-authored static-tier snapshot of
  an insighthealth-like page (HTML with header logo svg + og tags; 2 stylesheets exercising:
  custom props incl. a `prefers-color-scheme: dark` block, body/h1/button rules, @font-face
  with woff2 (tiny valid-enough bytes), rem sizes, rgb() colors, var() resolution; 3 images
  + 1 og:image; a trial-font filename). `snapshots/spa_shell.json` — near-empty body, 1 js
  bundle, no stylesheets. `snapshots/insight_rendered.json` — computed_samples +
  custom_props present.
- parse tests: role hints land (body bg → page-bg weight 5, button bg → button-bg), dark
  block colors get theme="dark", var() resolves, rem→px, font-face preference order +
  license hints, logo vs og:image split, image cap logic.
- gate tests: insight_static → no escalation; spa_shell → escalate reasons; escalate w/o
  render_available → LUMI0506 + static outcome.
- capture_website plumbing: fake transport (httpx.MockTransport) serving a small site →
  assert stylesheets and assets were fetched CONCURRENTLY (record request start/finish
  ordering via the mock handler + an asyncio.Event barrier — e.g. respond only after N
  requests are in flight; a serial implementation deadlocks/times out, a concurrent one
  passes) + redirect re-guard (redirect to 127.0.0.1 → rejected).
- SSRF: guard_url rejects localhost/127.0.0.1/10.x/169.254.x/[::1]/file:/ftp:, accepts
  public https.
- evidence_builder: with a stub CoreClient (records ingest_asset calls) → asset ids
  content-addressed, faces wired, evidence validates as BrandEvidence, screenshot listed.
- end-to-end replay: insight_static snapshot → parse → build_evidence(stub core) →
  normalize_evidence → kit passes CoreClient().validate_brand_kit(product_ready=False)
  (real helper, like slice 0's round-trip).

Agent B — `test_ingestion_routes.py`:
- POST with stubbed capture (monkeypatch pipeline.capture_website with an async fn returning
  a loaded fixture outcome… import the snapshot via lumen_ingestion.capture only for
  loading; if Agent A's fixtures aren't present yet, author a minimal inline
  CaptureOutcome) → TestClient runs background task on response → GET shows succeeded +
  brand_kit_id; kit exists via GET /brand-kits/{id}; brand_summary_json contains
  "ingestion" key; source == "website"; attach to a document via POST
  /documents/{id}/brand-kit succeeds (DoD).
- Failure path: capture raises → job failed, error_json populated, GET returns error, no
  kit row.
- SSRF 422 on http://127.0.0.1:8080, file://, url with credentials.
- Stage progression: reporter stages recorded on job row during run (assert final stage
  "Preparing your brand kit…" reached / progress ≥ 0.85 before success).
- Route ordering: GET /brand-kits/ingest/{job_id} does NOT hit the kit-detail route (404
  code path distinct).
- Live e2e (skipped unless `LUMEN_INGESTION_LIVE_E2E=1`): POST real URL
  (https://www.insighthealth.ai), poll until done, assert kit populated.

## 11. Diagnostics namespace (slice 1)

LUMI0501 blocked URL (error) · 0502 size cap (warning) · 0503 fetch failure (warning) ·
0504 image cap (info) · 0505 escalated to rendered (info) · 0506 escalation unavailable
(warning) · 0507 html truncated (warning) · 0508 render timeout fallback (warning).
Capture diagnostics flow into the persisted kit diagnostics alongside normalizer ones.

## 12. Verification

`cd apps/api && LUMEN_CORE_HELPER=<repo>/target/debug/lumen-api-helper ../../.venv/bin/python
-m pytest tests/test_ingestion_capture.py tests/test_ingestion_routes.py -x -q` then full
`pytest tests -q` (expect 107+new passed, 2 pre-existing skips + live-e2e skip). No engine
changes; no WASM rebuild.
