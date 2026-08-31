# 2026-08-25 — Ploy competitive study: why their cloned pages are brand-coherent, vs our ingestion

Analysis-only session (no code changes). Founder shared transcripts of Ploy's agent explaining its
brand ingestion + logo strategy, and asked for a forensic comparison of
https://my-site-c00a8643.ploy.build/abm/goodman-campbell vs https://www.insighthealth.ai/, mapped to
improving our design editor's website output quality. Evidence gathered by fetching both pages' HTML
+ CSS and full-page screenshots; our pipeline mapped by an Opus explorer over
`subsystems/clue-design/` (report summarized below).

## Hard evidence of what Ploy actually does (from their shipped page, not their marketing)

1. **They clone, they don't re-derive.** The ABM page's nav/hero/security/testimonial/footer are the
   original Webflow DOM transliterated into Astro+Tailwind: original class names preserved verbatim
   (`nav_logo`, `section_home-hero`, `w-dropdown-list`, `w-nav-brand`, `home-security_badge`),
   original alt texts, verbatim copy ("Safe, Secure & Compliant", the full Dr. Medress paragraph),
   nav hrefs pointing back to the real insighthealth.ai pages.
2. **Exact font binaries re-hosted.** Aeonik OTFs pulled from Insight's Webflow CDN and served from
   cdn.ploy.ai — the Webflow file IDs survive inside Ploy's filenames
   (`23b02936-6799cf04eafb94b1622e6922-aeoniktrial-regular.otf`).
3. **All images slurped + re-hosted** with provenance-preserving names (`slurp-<webflow-id>-<orig-name>.webp`),
   a few still hotlinked to the Webflow CDN.
4. **Tokens come from the source site's own CSS variables.** Webflow sites declare their palette
   (`--base-color-brand--green:#30d8a7` etc.); Ploy maps those 1:1 to semantic roles and converts to
   OKLCH exactly: mint→`--ploy-accent-primary: oklch(78.8% .15 167.76)` (verified by conversion math),
   navy→accent-secondary/neutral-inverse, lavender→accent-tertiary, shell→neutral-light. Then:
   generated 50–950 ramps per role, auto-derived dark theme (lightness-flipped, chroma/hue kept),
   s0–s5 surface tints via color-mix, `--ploy-button-primary-{background,border,text}` component tokens,
   all bridged onto shadcn-style `--background/--card/--accent` vars.
5. **Effects transliterated token-relative.** The original's 5-layer shadow
   (`0 7px 16px #231e400f, … 0 184px 51px #231e4000`) re-emitted as Tailwind arbitrary values with the
   navy-alpha hexes rewritten to `color-mix(in srgb, var(--ploy-neutral-inverse) 6%…0%, transparent)` —
   same pixels today, theme-safe forever.
6. **States survive because source CSS is kept** (hover = navy bg / shell text on the mint pill,
   `rounded-[10rem]` pill geometry) — read from stylesheet rules, not sampled from a screenshot.
7. **Target-account logo = canonical-site authority ladder**, hotlinked:
   `https://www.goodmancampbell.com/wp-content/uploads/2025/09/goodman-alogo.svg` (visible nav SVG of
   the canonical domain), used sparingly as co-brand chip; seller brand stays dominant.
8. **New ABM sections (`abm-alignment`, `abm-product-value`, `abm-demo`) are fresh compositions that
   only speak the token vocabulary** — coherence of new content comes from the token system; coherence
   of everything else comes from literal reuse.

**Core insight: fidelity = preservation, not reconstruction.** The cloned site IS the component
library; a new page is ~70% reused original components with new copy + ~30% new token-lawful sections.

## Our pipeline today (Opus explorer report, key facts)

Strong at *measurement*: forced rendered-tier capture (Playwright 1440px, scroll-settled), measured
geometry per component class (radii/padding/borders/shadows/bands/focus rings), `surface.band.*`
minting, font binary download AND serving (`web_export.py` @font-face), OKLCH-derived 41-color role
set, BrandBrief with component recipes, draft human gate, kit-relative fidelity scoring.

Gaps vs Ploy (largest first):
1. **Captured HTML/CSS is discarded** — only `BrandEvidence` persists; generation composes fresh pages
   from a generic section grammar (`knowledge/web/landing-page.md`). No component/section reuse at all.
   `SurfaceShape`/`SectionBackground` are measurements *about* components, not the components.
2. **Single page only**; no site crawl, no responsive/mobile capture.
3. **No hover/active state capture** (only focus geometry, and the measured outline color doesn't even
   feed the `focus.ring` token — it's derived from ramp-500).
4. Source CSS custom props used only as weighted color *evidence* (weight 3.0), not as role
   *declarations* — we ignore the highest-fidelity signal on Webflow/Framer-class sites.
5. Assets capped (50 images/16 described), alt text NEVER read, no structured provenance (logo score
   serialized into a locator string), no DOM-position/bbox record, no customer-logo-wall detection.
6. Website-path logos have **zero light/dark/reversed variant detection** (only the upload path has
   `_logo_hints`); the recurring `bytes_missing` has a real mechanism: the logo *scorer's* candidate
   pool (JSON-LD/og:logo-declared URLs, logo-class ancestors) is strictly wider than the *fetcher's*
   list (`static.py` fetches header/nav/logo-class imgs + favicon + touch-icon only) → the top-scored
   candidate can carry no bytes and gets silently dropped (`evidence_builder.py:107-119,167-169`).
7. **No render-and-compare against the source site** anywhere — source screenshots are used once as
   brief-agent vision input; the visual reviewer only critiques the generated page in isolation.
8. Font face bytes frequently fail to download (cursor.com: 4 families evidenced, 0 non-icon binaries)
   and license is hardcoded non-embeddable.

## Direction implied (NOT implemented — founder to ratify)

- A "site clone" capture tier that persists DOM+CSS and transliterates key sections (nav/hero/footer/
  proof/testimonial) into seeded, token-bound reusable components (founder explicitly OK with these
  being partially non-editable in the editor if output quality matches).
- Read source CSS rules for hover/active; treat source CSS variables as role declarations when present.
- Slurp-and-rehost all assets with provenance-preserving names + structured evidence records
  (alt, DOM role, link destination, occurrences, background context, numeric confidence).
- Target-account logo ladder for ABM co-branding (canonical domain → visible nav mark → JSON-LD →
  brand page → favicon; light/dark detection; confidence gate → needs-review, never synthesize).
- Close the scorer/fetcher pool mismatch (fetch everything the scorer may score).
- Add a render-and-compare loop: generated page screenshot judged against the stored source screenshot.

Full raw artifacts from the study session: /tmp/ploy-study/ (both HTML files, both CSS files, both
full-page PNGs) — temp only, will not survive reboot.
