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

## Phase 1 SHIPPED (2026-08-30, two commits on integration/frontend-design-part-iv-v4)
Founder approved scope: computed values + census first, logo = Phase 2, multi-page = agreed
follow-up. Landed (commits "render probe + pixel census" + "rendered-truth palette election"):
- `capture/rendered.py`: _PROBE_JS (probe-resolved tokens, visible element samples w/ boxes,
  media boxes, gradient stops, canvas fraction, viewport width), Escape+overlay removal
  (LUMI0530), 3s hero dwell, reduced_motion=no-preference, LUMI0532 probe-fail diag;
  `SiteSnapshot.render_probe` (optional, back-compat).
- `lumen_ingestion/census.py` (new): PIL point-LUT + getcolors census (NO numpy dep),
  diversity-aware photo masking, fold census, button region modals, accent-text +
  gradient-stop families, resolved tokens → `RenderTruth` (new models in evidence.py;
  `BrandEvidence.render_truth` optional). PASTEL_C moved to colorspace.py (import-cycle-safe).
- `normalizer/roles.py`: `_assign_from_render_truth` — tiered election (buttons≥2 → gradient
  area → accent text≥2 → pastel fold census → single button), census presence = veto,
  basis="measured" (0.8 confidence, pre-existing), evidence strings in provenance,
  LUMI0531 blocked-capture flag, and `_visible_declaration`: a DECLARED role must also be
  visible on the rendered page (LUMI0534) — live-caught apollo's
  `--PhoneInputCountryFlag-backgroundColor--loading` #0000001A declared as surface.page.
- `capture/parse.py`: rule-text palette candidates RETIRED; `_selector_role` deleted.
  ONE deliberate survivor: dark-block rule colors, flat weight 1.0 hintless (dark capture
  deferred; build_dark_colorway has no census substitute). Custom-prop/token evidence,
  declared roles, fonts, state records all kept.
- Tests: `tests/test_ingestion_render_truth.py` (11 tests incl. apollo red case, invisible
  declaration, blocked-capture flag, ranking fix, retirement guard); 3 legacy tests rewritten
  to the new contract (they asserted the retired behavior). Focused files green (107 pass).
  KNOWN pre-existing env failure, NOT mine: test_ingestion_brief.py::
  test_approval_does_not_mutate_the_brief — local dev DB missing `design_web_fragment`
  migration (approval→web-fragment sync path).
- LIVE-PROVEN on production code path (.context/poc-brand-colors/live_pipeline_proof.py):
  apollo.io → page #FFFFFF / brand #ECF414 / text #212121 all [measured];
  sarvam.ai → brand #A5BBFC (gradient stops + token). Full apps/api suite running in
  background at session end (/tmp/full_api_suite.txt).

## Capture PoC (2026-08-30 evening, founder-requested before committing): Scrapling WINS, GPU-Chrome hypothesis FALSIFIED
`.context/poc-brand-colors/capture_poc.py` (throwaway). Findings:
- REAL headed Chrome + GPU + webdriver-flag hidden + pointer-on-hero does NOT paint sarvam's
  WebGL aurora (97.7% white; webgl2 canvases exist, stay blank). The gap is CHROME-AUTOMATION
  fingerprinting / site-conditional rendering, NOT headless/GPU. Do not invest in GPU flags.
- Scrapling StealthyFetcher (camoufox/Firefox, v0.4.11 in root venv) PAINTS the aurora:
  saffron #FC7414/#F4842C ~12.5% + indigo/periwinkle 5.6% — the founder's screenshot palette.
- Scrapling also defeats both bot walls: ramp.com serves its REAL styled page (3.9MB html,
  lime CTAs visible; previously the unstyled "machine version") and openai.com serves its real
  dark landing (#040404 77%; previously Cloudflare human-check).
- Integration path: camoufox's page_action hands a playwright-compatible Page, so
  _EVALUATE_JS/_PROBE_JS/screenshot run as-is — swap the launcher in fetch_rendered (or a
  sibling fetch_rendered_stealth), keep probe/census/election unchanged.
- Hazard observed live: headed browsers open on the founder's screen and they may interact
  (mega-menu incident); keep stealth captures headless.

## Stealth backend SHIPPED (2026-08-30 late, commit 614803b24)
- Correction to the earlier capture-PoC note: scrapling 0.4's StealthyFetcher is a stealth-
  HARDENED CHROMIUM (fetchers/stealth_chrome.py), NOT camoufox/Firefox. Same engine as ours,
  async_fetch + async page_action → shared harvest code.
- `fetch_rendered` = dispatcher: stealth default → plain-Chromium fallback; provenance always
  stamped (LUMI0535 stealth info / LUMI0536 fallback warning); kill switch LUMEN_RENDER_STEALTH=0.
  Page driving extracted to one `_harvest_page` used by both backends (no drift possible).
- CRITICAL FINGERPRINT LESSON (cost ~3 debug rounds): pass NO additional_args/context overrides
  to the stealth session. Overriding viewport to 1440x2000 broke scrapling's coherent
  fingerprint and sarvam's aurora refused to paint; scrapling defaults → paints. Probe records
  live viewport_width so census scale is independent. Also falsified en route: full-page vs
  viewport screenshot was NOT the variable.
- Production-path proof: sarvam brand #FCCCA4 (4 rendered buttons, warm saffron) + accent
  #A5BBFC (indigo, gradient+token) — BOTH families the founder demanded; apollo #ECDC7C yellow
  family, page/text right. Comparison sheet: .context/poc-brand-colors/out/pipeline-runs/
  compare.html (render_compare.py; dumps via live_pipeline_proof.py <url> <label>).
- scrapling>=0.4,<0.5 declared in apps/api requirements.txt + pyproject.toml.
- FULL apps/api suite classified (was 293 FAILED): 2 were ours (test_ingestion_asset_slurp
  completion-sentinel used rule-text colors → fixture now declares a :root token; FIXED, 35/35
  green), remaining ~291 are PRE-EXISTING local-dev-DB migration drift — `design_web_fragment`
  and `design_site_snapshot` tables missing (web-fragments/campaign-shell/ad-assets/approval
  test families + test_workspace_seam). Env repair needed: run the design migration chain on
  the local dev DB. Not done this session (shared-DB state change; founder to green-light).

## Acceptance sweep DONE + record CORRECTION (2026-08-30 night, commit b8e6c86a7)
- **CORRECTION — the "291 pre-existing DB-drift failures" claim was WRONG.** The dev DB
  (`clue_colombo:55040` from .env) is fully migrated; my pytest invocations simply never
  sourced `.env`, so `clue_db.database_url()` fell back to DEFAULT_DATABASE_URL — a stale
  local DB missing the fragment tables. With `set -a; source .env; set +a` the previously
  "failing" families are green (test_web_fragments + test_ingestion_brief: 49/49). RULE:
  design-subsystem pytest ALWAYS needs .env sourced (matches the dev-stack runbook memory).
  Full suite re-running with proper env in background at session end (/tmp/full_api_suite3.txt).
- Stealth-path acceptance sweep, production code, 7 brands all correct:
  apollo #ECDC7C yellow | stripe #543CFC + accent #60A8E2 | sarvam #FCCCA4 saffron +
  #A5BBFC indigo | workspan navy+violet+cream (declared, visibility-verified) |
  ramp #E4F424 lime (site that served the bot "machine version" before stealth!) |
  openai dark scheme #040404/#041424/white | freshcontext all-declared cream/orange/brown.
  Sheet: .context/poc-brand-colors/out/pipeline-runs/compare.html.
- Stripe live finding fixed (b8e6c86a7): declared-accent-vs-brand dedup is now PERCEPTUAL
  (OKLab MERGE_DISTANCE), not exact-hex — #533AFD beside #543CFC was the same blurple.

## Full-suite verdict with proper env (2026-08-30 close)
31 FAILED (down from the bogus 293) across env-sensitive families, ALL classified NOT-ours:
- test_ingestion_grammar_audit job-poll failures REPRODUCE AT THE PRE-PHASE-1 COMMIT
  (worktree check at 30bdf7d7c, same env: 3 FAILED) — pre-existing branch/env issue
  (ingestion-job polling against the accumulating shared dev DB; conftest itself says to use
  a disposable CLUE_DATABASE_URL).
- custom_component families (16): need the node toolchain + vendored tailwind runtime
  (AGENTS.md §5) not present in this workspace.
- test_api W14/W17 gateway tests (4): the sourced .env carries REAL api keys, which changes
  gateway behavior these tests pin against no-key defaults.
- asset custody/serving, web_turn base-url, web_fragment_render leftovers: same env classes.
Canonical green full-suite run needs a curated test env (disposable DB, scrubbed keys, node
toolchain) — dev-infra follow-up, unowned. Every ingestion/render-truth/stealth-touching test
family is green under the proper env.

## Phase 2 (logo corroboration) — DEFERRED INDEFINITELY (founder ruling 2026-08-30)
**Founder decision at close: Phase 1 is the shipped scope; Phase 2 happens only "if ever the
need comes and the need is felt." Do NOT start it in a future session without a fresh founder
go.** The full design + sizing is preserved below so a future pickup starts here, not from
scratch. (The "GPU/scrapling capture" follow-up listed in earlier drafts is DONE — that became
the shipped stealth backend; multi-page capture and approval-UI evidence surfacing remain
open, also unscheduled.)

### Preserved Phase-2 design (ratified in discussion, never implemented)
Value: (a) the logo is the only evidence source with a CHOSEN answer — the election anchor for
sites whose brand lives in text/washes (sarvam-class) or heavy-photo pages; (b) dark/light
logo variant selection from measured per-variant palettes (ink colors + luminance) instead of
filename/color_mode_hint heuristics — feeds `logo_policy.allowed_backgrounds_for` with pixel
truth; (c) "kit brand color appears in the logo" as a cheap approval-time sanity assertion.

Work breakdown (total 3–4 days; lean slice A ≈ 2 days):
1. `logo_colors.py` (1–1.5d) — dual-pass extraction on logo_ladder winners:
   SVG markup pass (fills/strokes/stop-colors/inline styles/style blocks via tinycss2;
   SKIP masks, clipPaths, hidden/opacity-0 elements, `url()` paint refs, non-colors;
   all hex forms + rgb/hsl + named colors; `currentColor` screen — ladder already detects it
   and records the observed ink) + raster pass (existing `rasterize_svg` engine seam for SVGs,
   PIL for PNGs; alpha-reject ≥128 floor, NO lossy resize, exact-count histogram, guarded
   achromatic filter, OKLab merge via existing census helpers) + reconcile (markup = exact
   values + gradient endpoints census can't see; pixels = visibility proof; both-found = most
   trusted).
2. Election wiring (~0.5d) — logo colors as corroboration source in the tiered election
   (logo-match anchors a candidate; brand-vs-logo contradiction → review flag; evidence
   string "appears in the logo").
3. Variant color modes (~1d) — measured per-variant luminance/inks verify-or-correct
   `color_mode_hint`, real contrast vs elected page/dark surfaces → dark-mode/light-mode
   variant selection. SCOPE BOUNDARY: stays slot-level; the per-variant
   `allowed_backgrounds` needs a Rust `LogoVariant` field (engine change + wasm handshake
   ceremony, ~1d separate follow-up, documented limit in logo_policy.py).
4. Golden logo fixtures + 7-brand sweep re-run (~0.5–1d) — trap cases: gradient stops,
   `currentColor`, mask/clip decoys, transparent PNGs.
Risk: low, purely additive — a weird logo degrades to "no logo corroboration, Phase-1
election stands" (today's behavior).

## Open items for Phase 1
- Where election evidence strings surface in the kit approval UI (founder wants auditability).
- Threshold calibration → golden-brand regression fixtures (apollo yellow/black red-case first,
  then the 12-brand sweep as before/after acceptance).
- Dark-scheme capture deferred by founder scope-cut (light-first); revisit later.
