# Gate G-D — engine-forced banners (ruled + built), 2026-08-21

Branch `integration/frontend-design-part-iv-v4`. Local commits only.

## The ruling

Founder, on the three G-D states: *"approve them as is from the mvp editor only, no separate
banner needed, but show me a preview of how those errors would look. secondly, for readonly
also keep them same as that in other mode only."* After the rendered preview: *"all 4 previews
look good... proceed with them just the way you showed them to me."*

Read as: port the MVP editor's own banners verbatim, design nothing new, and give the
read-only (engine-stamp/handshake) state the same treatment as degraded text rather than a
bespoke canvas surface. The founder saw an alternative with the developer command line removed
and did **not** take it — the command chip ships.

## Preview method (worth repeating)

The four states were rendered on the REAL ad by injecting the upstream banner markup + CSS into
the live canvas stage through the gstack browse daemon (`window.__gd(mode)` in
`/tmp/gd-preview.js`), screenshotting, then removing it. No code, no commit, no mockup file.
Screenshots `/tmp/gd-*.png`. The injection immediately exposed a defect a static mockup would
not have: upstream's translucent wash is unreadable over a dark artboard.

## What shipped

- `src/features/design-editor/adapter/scene-engine-banners.ts` — the copy, as a pure function
  of `(engineStatus, measurementStatus)`. Empty array is the normal answer.
- `scene-engine-banners.test.ts` (7 cases) — behaviour + a **verbatim guard**: every sentence
  is asserted to exist in
  `subsystems/clue-design/apps/editor/src/components/EditorChrome.tsx`, so an edit on either
  side fails the build instead of silently forking the two editors' voice.
- `scene-artifact-canvas.tsx` → `SceneEngineBanners`, mounted inside the canvas stage (not the
  shell): the stage is the one surface both mounts share, so the artifact route and the chat
  route get it with zero plumbing, it survives the inspector being closed, and both inputs are
  already local to that component.
- `scene-artifact-canvas.module.css` → `.bannerLayer/.banner/...`, the upstream block with its
  tokens resolved to literals (the platform shell defines no `--status-error*`).

## Three deviations from a literal copy (all disclosed before the ruling, all taken)

1. **Opaque background.** Upstream `rgba(207,45,86,0.15)` assumes an always-light workspace;
   over the navy ad the body text disappeared. `#efd7dd` is that wash composited over
   `--bg-canvas` — same colour, not see-through.
2. **The banners stack.** Upstream pins both at `position:absolute; top:14px`, so a
   simultaneous engine + measurement failure would paint one on top of the other. Ours is a
   flex column.
3. **The command chip names this repo's command** (`npm --prefix
   ../../subsystems/clue-design/apps/editor run build:wasm`, which is the string
   `scripts/copy-design-vendor.mjs:96` already prints, and `node scripts/copy-design-vendor.mjs`
   for the canvaskit/font case). Upstream's `npm run build:wasm` / `build:canvaskit` do not
   exist in `apps/frontend`.

Plus one non-visual addition found by the browser proof: our longer command truncates the chip
(upstream's `white-space: nowrap` + ellipsis), and the truncated part is the *detail* — the two
engine hashes, i.e. the diagnosis. A `title` attribute restores the full string on hover with
zero visual change. The console diagnostic still carries it too.

## Browser proof (forced REAL failures, not injection)

- **Degraded text:** `public/vendor/fonts/` moved aside → CanvasKit loads, font registration
  fails → `data-scene-text-measurement="heuristic"`, one banner, and the ad's text genuinely
  vanished (exactly what the copy warns about). `/tmp/gd-proof-heuristic.png`.
- **Engine disabled:** `window.fetch` patched to fail `/build-info` before the canvas mounts →
  `handshake_failed` with the real detail string, scene still rendering from the server
  snapshot. `/tmp/gd-proof-engine.png`.
- **Both, stacked:** `/tmp/gd-proof-both.png`.
- **Healthy:** engine `wasm`, measurement `skia`, **zero** banner elements, clean console.

Note for future forcing: `activateEngineOnce` memoises per PAGE LOAD, so the fetch patch must
be installed after `goto` and before the ad card is clicked. Killing the design API is *not* a
good proxy for this state — the document fetch dies with it, so you get a load error instead of
a rendered-but-read-only canvas.

## Gate: frontend 1421/1421 (7 new), lint clean (3 pre-existing warnings in ported files),
`npm run build` green. No Python touched, so no root `make check` needed.

## Ledgered

Contract amendment 4 + §6 item 5 closed; plan register G-D marked RULED & SHIPPED. §6 mockup
queue is now four items: selection handles, palette-departure note, crop focal dot, export
print-extras. The CAS-conflict half needs no further work — `ImageInspector` already carries
the `note` slot from AD2.7; AD3's committer supplies "Document moved on — reloaded."
