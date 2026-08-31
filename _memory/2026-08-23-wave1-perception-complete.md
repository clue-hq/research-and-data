# 2026-08-23 — Wave 1 (perception) CODE-COMPLETE; live exit gate pending on stack ownership

Branch `integration/frontend-design-part-iv-v2`, base `980921e5` → head `2664ba700`
(13 commits). Plan: `docs/superpowers/plans/2026-08-22-design-quality-waves.md`
Wave 1. Process: subagent-driven development — Opus implementers, controller
inline review + Opus task review per slice, scoped re-reviews, final Opus
whole-branch review + one fix wave. Ledger (rulings, deferred minors, evidence
paths): `.superpowers/sdd/2026-08-22-design-quality-waves/progress.md`
(gitignored scratch — this file is the durable summary).

## What landed (all task-reviewed, all fix rounds closed, suites green)

- **W1.1** `view("asset:<id>")` on the web lane (commits 80557d4a, 7bedc4ca):
  shared resolver `tools/asset_preview.py`; resolves document registry → kit
  manifest → workspace library; reports SOURCE + preview dims; four honest
  outcomes; G5 2000px clamp; id menus capped at 12/source.
- **W1.2** SVG raster thumbnails at ingest (7e9660e9, 2dbb4c9c, 705f81ae):
  `lumen-skia::rasterize_svg_thumbnail` (existing skia svg::Dom, no new dep),
  helper wiring with silent fallback, did-anything-paint guard (blank SVG →
  legacy arm), resolver skips non-raster thumbnail mimes (legacy records degrade
  honestly), cross-crate size-policy parity test. All kit-asset producers route
  through helper IngestAsset (reviewer-verified) — new ingests get real PNG
  thumbnails; legacy kits stay shape-1 until re-ingested.
- **W1.3** brand card truth (3ccf526f): `engine_mirror.py` = the ONE Python home
  for sanitize/resolve/css-ok/dims; px on image+logo rows (needs the
  `asset_manifest` kwarg both lanes now pass); color roles carry class-shaped
  `token` + the transposition-killing note; `web_theme_token_names` replicates
  both Rust skip rules; drift test harvests the COMPILED vocabulary via a real
  LUMW0212 rejection through the helper.
- **W1.4** describe on by default (c2fcfc98, c43bb6b8): probe-chosen
  `google/gemini-2.5-flash-lite` ($0.000208/caption ≈ $0.0042/ingestion; 8
  candidates live-probed), top-16-by-area ∪ all logos (ranked over the IMAGE SET
  then intersected with cache misses — the cache-rank leak is fixed+RED-proven),
  SVG logos described via their W1.2 thumbnails, keyless deployments inert.
- **W1.5** search_assets fixed (4a11b8e9, 4a6b8789): root cause = kind filter
  compared agent vocab "image" to engine kinds with == (allow-list now:
  raster_image/vector→image, logo, font, others stay raw — no PDFs as images);
  three-manifest scan; ranked token matching (3-char substring floor);
  px + `view: asset:<id>` on rows; honest empties naming inventory; grounding
  cap never drops rows (annotated); card sorts by record dims.
- **W1.6** scope collapsed: force-render had ALREADY landed 2026-08-20
  (`c9bf2859`, founder ruling, tested) — plan was drafted from a stale memory
  record; the embedded-worker `GeometryEvidence` ImportError was root-caused
  live 2026-08-19/20 as a STALE SIBLING PROCESS leasing jobs (C15 fence class,
  Wave 4 owns). Remaining deliverable landed: `LUMEN_INGESTION_BRIEF=1` in BOTH
  recipes (subsystem + root .env.example) + two-recipe parity test.
- **Final fix wave** (0c94fb86, 2664ba70): search registers grounding for
  library-origin rows ONLY (kit/doc rows never spend the 64-slot budget);
  row-wise paint-guard read-back (halves peak memory); prompt/docstring honesty
  fixes.

Suite: 664 → 752 collected, exit 0 (agent_runtime); cargo workspace green;
helper rebuilt. This workspace's skia goldens + visual baselines are UNTRACKED
local artifacts — regenerate in any fresh worktree via UPDATE_SKIA_GOLDENS=1 /
UPDATE_LUMEN_VISUAL_BASELINES=1 or cargo test fails on missing files.

## Live exit gate — NOT yet run, blocked on stack ownership

Gate: (a) UI re-extract of stripe.com publishes a draft kit with measured
geometry AND BrandBrief@1; (b) fresh generation where the director cites assets
it viewed via `view("asset:…")` (trace-proven), search returns non-zero, card
shows dims; (c) no new UI surface (already verified in review). Preconditions:
exactly ONE design API on 801x + fleet worker on the NEW helper; live untracked
`.env` needs `LUMEN_INGESTION_BRIEF=1`; no run in flight; kit v6 stays approved
(v8 approval remains the founder's — ruling R1 still open).
**Blocker at close: port 8010 is held by the COLOMBO workspace's design API
(pid 21299) — another worktree's server; taking it over needs the founder.**

## Key deferred items (full list in ledger; final review triaged)

- `_brand_notes` filters the `accent` DICT out of image-generation notes
  (pre-existing; highest-value deferred item; home = W4.1).
- Describe/card ranking-source upgrade (true raster dims so CSS-background
  heroes rank; one coherent later fix, both sides).
- Grounding-contract question: should search-time registration gate placement
  at all (W4); stale source_id on non-library rows → loud refusal (accepted).
- `_ASSET_DISPLAY_KINDS` second engine-vocab copy → move to engine_mirror + an
  AssetKind drift guard (post-gate cleanup with the 3 thumbnail predicates).
- Thin-vector upscale policy (256×1 → 67MP) belongs to the thumbnail policy
  owner; W1.2 inherited it.
- apps/api whole suite unusable as a gate under sibling-workspace contention on
  shared dev Postgres (C15 kin; per-workspace DBs wanted).

## Wave sequencing (founder, 2026-08-23, follow-up pending)

Founder asked to run Wave 3 BEFORE Wave 2 — controller confirmed it is safe (no
dependency; sequential Rust on the shared crate; two honest costs: Wave 3 walks
run on the fragile page-voiding write path until W2.1; Wave 2's latency wins
arrive later). Controller recommended pulling W2.1 alone ahead of G1.
**Founder has not yet chosen** strict-Wave-3-first vs the W2.1 amendment.

## Addendum 2026-08-23 (post-wave, founder-ordered): model defaults + gpt-image-2

- **Model defaults flipped (6a416d7c8 + 94ea6c131):** agent model
  `openai:x-ai/grok-4.6` + `LUMEN_AGENT_REASONING=high` everywhere (code
  intrinsic default, root .env, both /tmp launch scripts, .env.example);
  terra/luna retired; image model `openai/gpt-image-2`. The reasoning "high"
  default supersedes the P3.2 "medium" gate finding (history preserved in the
  test comment). CLUE_SYNTHESIS_MODEL / CLUE_JUDGE_MODEL (platform research)
  deliberately untouched; describe/brief/vision stage models untouched per R4.
- **gpt-image-2 transport (5a89c843d + c41970b67):** OpenRouter's dedicated
  Images endpoint (POST {base}/images) via `IMAGE_MODEL_API_STYLE=images`
  (config `image_model_api_style`, default chat — Gemini-class chat path proven
  byte-identical). Body: prompt (+style framing when refs), aspect_ratio
  snapped to the closed enum {1:1,3:2,2:3,4:3,3:4,16:9,9:16,21:9}, quality
  always "high", background always "auto" (enum has NO transparent —
  transparency is prose-hint best-effort), input_references as typed image_url
  data: URLs (cap 16 asserted). Decode data[*].b64_json primary; url fallback
  follows redirects + rejects non-image/* typed. LIVE-VERIFIED 2026-08-23
  (founder raised the key limit; probe through the SHIPPED provider path):
  (1) base64 data: URLs in input_references ACCEPTED; (2) aspect_ratio honored
  exactly (16:9 -> 1536x864, 3:2 -> 1536x1024); (3) style-vs-copy: an abstract
  style anchor produced a NEW composition in its palette/rhythm, not a copy
  (logo-anchor case untested by design — logos never anchor). CRITICAL OPS
  FINDING: 67-75s/image at quality=high — the 60s IMAGE_MODEL_TIMEOUT_S
  default times out EVERY call (burns all 3 retries); recipes now set 240
  (root .env, both /tmp scripts, .env.example).
- **Ops learning:** frontend on 3030 MUST launch with
  CLUE_APP_ORIGIN=http://localhost:3030 (its .env.local pins 3020 → every
  mutation POST 403s REQUEST_ORIGIN_FORBIDDEN). In the /tmp recipes' spirit —
  add to any durable launch doc.
