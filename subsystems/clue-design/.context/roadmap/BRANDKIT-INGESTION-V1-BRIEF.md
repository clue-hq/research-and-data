# Brand-kit Ingestion v1 — kickoff brief (parallel workspace)

Written 2026-07-05 for a fresh Conductor workspace running parallel to Phase 3 (imaging) on the
main track. Base the workspace on `agents/editing-roundtrip-v0` (it carries the current
`crates/lumen-core/src/brand.rs` model and all Phase-4 work).

## Goal

Three intake paths that each produce a **DRAFT brand kit** a human then approves — taste stays
human-gated. Ingestion maps onto the EXISTING model; **no new schema**:

- `TokenCatalog` (brand.rs ~line 1169): colors, typography, spacing, radii, stroke_widths,
  opacity, shadows, effects, aliases.
- `BrandAssets` (brand.rs ~1352–1458): fonts (faces + license embeddable/subsettable flags),
  logos (variants fullcolor/onecolor/reversed/dark/light, usage, min_size, clearspace,
  allowed_backgrounds), images (role, style_tags, allowed_contexts).
- Kit row already has `approval_status`, `product_ready`, `source`, `brand_summary_json`,
  `diagnostics_json` (`apps/api/migrations/002_brand_kits.sql`).

## The three intake paths

1. **Web-scrape of a landing page.** Scrape URL → extract palette (computed styles / CSS custom
   props), font stacks + type ramp (h1..body sizes/weights/line-heights), logo (og:image /
   header img/svg), spacing rhythm, border radii. NOTE the big head start: `compile_styles_brand_kit`
   (`/brand-kits` upload path, `source="styles"`) already compiles CSS/styles into tokens — the
   scrape path can normalize scraped evidence INTO that compiler's input rather than reinventing
   token mapping. Firecrawl is available in the stack for fetching/rendering.
2. **Brand-guidelines PDF upload.** Parse pages (text + vision on rendered pages) → extract color
   specs (hex/CMYK/Pantone strings), type hierarchy, logo usage rules (clearspace, min size,
   allowed backgrounds — the model has fields for exactly these), imagery style notes →
   `BrandConstraints`. Embedded images that look like logos/marks → asset store + `BrandAssets.logos`.
3. **Individual asset uploads (SVG/PNG/JPG).** Register into the existing asset store (assets are
   referenced by `asset_id`, never embedded in the kit) + a `BrandAssets` entry with inferred
   metadata: logo-vs-illustration-vs-photo classification, variant detection (dark/light/mono via
   palette analysis), dominant colors (candidate accent tokens), transparency, colorspace/DPI into
   the existing raster metadata.

## Inference targets (all three paths converge here)

Heading scale / type ramp, accent + surface color roles, spacing rhythm, radii. **Hard constraint:
emit the same token ROLE NAMES the platform default kit uses** (surface.page, surface.inverse,
text.inverse, opacity.scrim, …) so agent briefs, the canvas resolver, and restyle work unchanged
on ingested kits. Diverging names = a silent compatibility break; put unmappable extras behind
aliases or kit-local names, and record gaps in `diagnostics_json`.

## Product rules

- Every ingested kit lands as `approval_status=draft`, `product_ready=false`, `source` set per path.
  Human review/approve is the gate (the approval UI itself can be minimal or even API-only for v1;
  the restyle slice on the main track becomes the real consumption surface later).
- Font licensing: conservative defaults — `embeddable=false`/`subsettable=false` unless provenance
  says otherwise (matters later for PDF font embedding in export hardening).
- `brand_summary_json` should get a human-readable summary of what was inferred and from where
  (evidence pointers), so review is judgeable.
- Multi-source merge (scrape + PDF + uploads for the same brand) may simply be "later ingestions
  create a new kit version" — versioning already exists (`(brand_kit_id, version)` PK +
  compatibility reports). Don't build a merge UI in v1.

## Scope fences (important — this is the parallel track)

- **API/Python only** (apps/api + a new ingestion module). Zero editor changes; engine (`brand.rs`)
  changes only if strictly additive and unavoidable — prefer none, to keep merges with the Phase 3
  workspace trivial.
- **Out of scope:** agent application of kit assets/theme in designs (merges into the main track
  AFTER Phase 3 — needs the agent-imagery path), Appearance/restyle UI, print constraint
  enforcement, content-schema anything.

## Definition of done (v1)

For each path: real input in → draft kit out with populated TokenCatalog + BrandAssets +
brand_summary_json, passing round-trip validation, visible via existing `/brand-kits` routes,
attachable to a document, and its colors/typography actually render when the platform-default
fallback is replaced by the attached kit (the canvas token-fidelity fix from 4d already resolves
attached-kit values client-side). Golden fixtures per path (a saved landing-page snapshot, a sample
brand PDF, a small asset set) so ingestion is regression-testable without network.
