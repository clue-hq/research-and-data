# 2026-08-30 — Brand-color ingestion PoC: computed values + pixel census beat the shipped stylesheet election

## Context
Apollo brand-kit ingestion elected cyan `#03B2CB` (a PhoneInput `:focus` custom prop) and
purple `#860DFF` (academy-page CSS) instead of Apollo's yellow/black. Root cause verified in
code: `capture/parse.py::_selector_role` hands out election-eligibility hints only for classic
selector vocabulary (`body`/`h1`/`button`/`.btn`…), so on hashed-classname frontends the real
CTA color earns weight 0.5 with NO hints (ineligible for `surface.brand` in
`normalizer/roles.py:223`), while `button:focus`-style rules inherit the `button-bg` hint at
4.0 — a focus ring outvotes the real brand. Internet research (colorize.design engineering
series, Brandfetch, Firecrawl branding format, DZone multimodal study) converged on:
three separate measurements (logo / computed tokens / rendered pixels), reconciled, never
averaged; stylesheet TEXT is obsolete as a value source (CSS Color 4/5); LLM eyes are ~53%
accurate on color — pixels are sampled programmatically, LLM labels only.

## Founder-ratified plan (this session)
- Phase 0 (DONE): PoC proving the difference. `.context/poc-brand-colors/poc.py`
  (gitignored, THROWAWAY), run from repo root: `.venv/bin/python .context/poc-brand-colors/poc.py <url>`.
  Uses root .venv (playwright+PIL+numpy all present).
- Phase 1 (next): productionize computed-values + census in `lumen_ingestion`
  AND REMOVE the stale method — stylesheet rule-text stops emitting palette candidates
  (the 5.0/4.0 `_selector_role` weight system + state-rule vector die together).
  Stylesheet parsing KEEPS its non-color jobs: font faces, interaction-state records
  (variants only, may never elect), custom-prop NAME discovery.
- Phase 2 (after Phase-1 testing on the 12-brand sweep): logo-color corroboration
  (logo_ladder already finds identity-verified logos + observed `currentColor` inks; its
  colors never fed election — that wiring is the phase-2 work; SVG dual-pass markup+raster).

## PoC results (before = real shipped code path: parse_site → cluster_colors → assign_light_roles)
- apollo.io BEFORE: brand `#03B2CB` cyan (from `--PhoneInput-color--focus` + button-text hint),
  accent `#860DFF`, page `#0000001A` (a flag-loading custom prop!) — bug reproduced live.
  AFTER: page `#FFFFFF` (76% census), text `#202020`, brand `#ECF414` yellow
  (modal color of rendered CTA buttons + 0.6% fold share). Correct.
- stripe.com BEFORE: accent `#D8351E` = their ERROR-icon token (`--hds-color-icon-error`) —
  same failure class, second brand. AFTER: brand `#543CFC` blurple (8 rendered buttons +
  their own token `--hds-color-accent-border-solid`), navy accents, white page. Correct.

## PoC lessons that must carry into Phase 1
1. Overlay hygiene: modals/cookie scrims poison both census and button sampling — remove
   full-viewport `position:fixed` elements (>25% viewport) + press Escape before screenshot.
2. Visibility filter: `el.checkVisibility({opacityProperty,visibilityProperty})` + area floor,
   else hidden menu items sample as phantom grey "buttons" (33 of them on apollo).
3. CTA colors are tiny by whole-page share (0.5–0.6%) — button-region evidence must ELECT
   directly (census presence is the veto, not the gatekeeper), and census should weight
   above-the-fold rows (long pages drown hero colors; apollo page = 13,363px).
4. Resolved-token corroboration works (probe-element `var()` resolution; unregistered props
   don't resolve via getComputedStyle alone — the probe is mandatory).
5. Media masking: `img/video/canvas/picture` + `background-image: url(...)` boxes; apollo's
   golden hero is imagery (~43% of pixels masked) — brand yellow still wins via buttons.

## Iteration 2 (2026-08-30, after the 5-site sweep + founder's sarvam.ai challenge)
Five more sites run (ramp, openai, sarvam, freshcontext, workspan; render.py builds the
before/after HTML sheet over all out/*/result.json). New findings + PoC fixes now in poc.py:
- ramp.com serves headless browsers an unstyled "machine version"; openai.com serves a
  Cloudflare human-check. Shipped method fabricated the platform-fallback teal `#0F766E` as
  "brand" on BOTH; Phase 1 must kill that fallback (flag, never invent) and route capture
  through Scrapling (platform default backend) for anti-bot.
- workspan.com: strong triple-corroborated win. freshcontext.ai: ranking flaw — 1-button
  candidate outranked token-corroborated fold colors → single-button evidence demoted to the
  weakest tier (fixed in poc).
- sarvam.ai (founder challenge — missed indigo/brown): FOUR method gaps + one capture gap,
  all now fixed/diagnosed: (1) computed gradient-stop harvest (getComputedStyle backgroundImage
  rgb() stops over large visible elements) — census structurally can't elect a gradient;
  (2) media masking made diversity-aware (photo = high-diversity stays masked; brand
  wash/aurora = low-diversity ramp stays IN census; sarvam masking 14%→5%);
  (3) chromatic accent-TEXT sampling (links/eyebrows/tabs) as a voting source;
  (4) pastel chroma floor 0.04 for census/gradient/text candidates (SATURATED_C=0.07 keeps
  gating buttons). Result: indigo family now elected (#A5BBFC + `--color-sr-indigo-300`
  token; brown #6C5C54 surfaced in census). (5) UNFIXED capture gap: sarvam's full-saturation
  saffron→indigo aurora is WebGL and does NOT paint in headless Chromium (SwiftShader) even
  with reduced_motion="no-preference" + 6s dwell — production needs GPU-enabled/headed
  capture (scrapling real-Chrome) for WebGL heroes. Election tiers now: buttons≥2 →
  gradient-stop area → accent text≥2 → fold census (pastel-eligible) → single button.
- Note: sarvam's BEFORE elected #393CC1 correctly *via token declarations* — the token-NAME
  semantic layer is the good half of the old method and survives in Phase 1; only rule-text
  mention-weighting dies.

## Open items for Phase 1
- Where election evidence strings surface in the kit approval UI (founder wants auditability).
- Threshold calibration → golden-brand regression fixtures (apollo yellow/black red-case first,
  then the 12-brand sweep as before/after acceptance).
- Dark-scheme capture deferred by founder scope-cut (light-first); revisit later.
