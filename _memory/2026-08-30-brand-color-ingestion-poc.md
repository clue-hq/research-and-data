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

## Open items for Phase 1
- Where election evidence strings surface in the kit approval UI (founder wants auditability).
- Threshold calibration → golden-brand regression fixtures (apollo yellow/black red-case first,
  then the 12-brand sweep as before/after acceptance).
- Dark-scheme capture deferred by founder scope-cut (light-first); revisit later.
