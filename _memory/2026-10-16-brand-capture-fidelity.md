# 2026-10-16 — brand capture fidelity (S6-1..S6-12 + page background)

Branch `brand/capture-fidelity` (from `puck/integration-wave1` @ faae10d6a), local only, not pushed.
Plan `docs/superpowers/plans/2026-10-16-brand-capture-fidelity.md`, spec `docs/superpowers/specs/2026-10-16-brand-capture-fidelity-design.md`.
Run subagent-driven: Opus implementers, controller reviewed every task first-hand; 6 fix rounds, all closed.

## What changed
- site-kit: `inkRole` uses a stored pair only when it reads ≥4.5:1; `.brand-root` paints surface.page + its text;
  `pageCanvasCss` puts `html{background-color;color;color-scheme}` in every rendered page head (walk defect 4).
- Parser: `lumen_ingestion/css_color4.py` (oklch/oklab/lab/lch/hwb/color()), matches Chromium pixels exactly; refuses
  what the browser refuses (CSS number grammar, exact channel count, no commas).
- Capture: `COLOR_FN` (geometry.py) — canvas colour reader + `behindOf` compositor through slots/shadow/iframes;
  section `bg` = composited colour behind it (white if nothing paints, null if an image is between).
- Band ink = colour covering most text area directly on the band (skips cards, sr-only/clipped text).
- Mint: band ink stored only if it reads; else kit text.primary/inverse (spec D4), else black/white; LUMI0609.
- Icons: computed paint written as attributes (currentColor when equal to text colour); sprite `<use>` → scaled `<g>`.
- Shadow DOM + same-origin iframes enumerated; state pass finds probes in any frame; CDP forced states via
  Runtime.evaluate → DOM.requestNode (getDocument depth 0 is enough; pierce cost 300 ms).
- Animations: every list entry kept (cap 12), `css_name` unescapes `glow\ pulse` / unquotes, U+FFFD for NUL/surrogates;
  stylesheets parsed once. Reveals re-found via `window[Symbol.for('lumen.reveal')]` (works in patchright too).
- Minting: within-style shared values named by shared places (`…hover-pressed.fill`, `…padding-y/-x`), source URL
  drops query/fragment, iteration counts use Rust f64 grammar (engine parity test is the oracle).

## Verification
- All `test_ingestion_*`, `test_capture_*`, `test_site_*`, css_color4, measured_components, export_parity etc. (78 files)
  green keyless, except 2 PRE-EXISTING (not this branch): test_capture_media_readiness (fake lacks web_doc, from main merge
  6841e7f24). tests/page_origin 36 green. tests/design: 274 passed, 6 failed — all pre-existing: p37 pinned turn (known),
  asset_upload_db + ingestion_pool_db teardown FK `workspace_hostname_workspace_fk` (main's tests vs website hostname FK).
- a9 scenarios end to end 15 + 1 pre-existing xfail; fresh A9 kit → site-kit 215/215, Brand page 108/108 incl. gated.
- Frontend lint 0 errors, site-kit typecheck clean, site-editor 64, production build compiled (throwaway in-repo copy).
- Visual: published Garner page in a dark-scheme browser paints rgb(249,250,248) with color-scheme light; min text
  contrast 6.38 even with deliberately broken stored pairs.

## Owed (founder-gated)
- Task 12 re-capture of Garner / Conduit / Clue (needs explicit yes + measured time estimate) — existing kits keep old
  stored values until then; Task 1 already makes them read correctly on screen.
- Live check on the lane stack needs the stack on this branch; lane DB is behind main's migrations since the PR #123 merge.
- Deferred minors: `_take_color`/gradient regex `[^)]+` cuts a colour with a nested var() alpha (pre-existing);
  script-set attribute strings with U+0000 are not NUL-sanitised before evidence storage (pre-existing).
