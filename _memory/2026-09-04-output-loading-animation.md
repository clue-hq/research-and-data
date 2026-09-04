# 2026-09-04 — Output-pane loading animation exploration

**Ask (founder):** the right-hand output pane is blank while the model generates an
artifact (LinkedIn ad etc.). Wanted brand-led loading animation options, modelled
loosely on Play's (blurred ghost + staggered 3D toys + shimmer label), plus the Clue
logo as standalone files, all in one separate folder.

**Delivered:** `.context/output-loading-animation/` (self-contained, open `index.html`).
- `animations/01-assembly.html` (mark pieces assemble/breathe), `02-segments.html`
  (Play-like stagger in Clue colours), `03-blueprint.html` (artifact wireframe fills per
  generation step, status panel), `04-develop.html` (artifact sharpens per step, crescent
  progress arc). Shared `shell.css` mimics the real screen and the reveal hand-off.
- `logos/01–05*.svg` + `logos/index.html`: mark on ink tile, mark olive, mark cream,
  lockup olive, lockup on ink. Geometry from `apps/frontend/public/icons/clue-mark.svg`
  and `~/Documents/clue-website/public/{favicon.svg,assets/clue-wordmark.svg}`.
- `reference/`: frames from the Play recording (extracted with a uv-fetched
  `imageio-ffmpeg` binary; no system ffmpeg on this machine) + today's screenshot.

**Verified:** all four pages + the logo gallery screenshotted via gstack browse at
1400x900; no console errors; Finish hand-off renders the finished ad mock.

**Notes / gotchas:**
- Conductor attachment filenames contain U+202F before "AM" — glob them, don't type them.
- `~/Downloads/Clue Design System/` is an older oxblood-coloured brand exploration that
  contradicts production (olive/sage + Satoshi). Don't use it as source of truth.
- Recommendation recorded in the folder README: options 3/4 if step events are exposed
  to the frontend (they are on the project run stream); option 1 for pure brand moment.

**Open:** founder to pick a direction; nothing is wired into `apps/frontend/`.

## Round 2 (same day) — founder review → production handoff

Founder liked Option 1 (Assembly) and refined the brief: two animations covering
the **whole output pane**, brand colours only. Website = blur until the page
exists (can't stream). Ad = artwork visible + live, input locked, Moda-style pill
"Currently designing. Please wait to edit." Both get a Comet-style perimeter glow.
References were two recordings of Moda running inside the Comet browser (glow =
soft haze hugging the pane edges; Moda pill = frosted, top-left, blue shimmer text).

Delivered in `.context/output-loading-animation/`:
- `handoff/generating.css` — the single motion source (class prefix `clue-gen-*`,
  token vars with hex fallbacks, reduced-motion block; glow z-index 7 above veil/lock 6).
- `handoff/{clue-mark,generating-glow,website-generating-veil,ad-designing-lock}.tsx` + `index.ts`
  — house style (named exports, `cn` from `@/lib/utils`, `data-active`), no `motion` dep.
- `handoff/HANDOFF.md` — mount points (`artifact-stage.tsx`, `web-artifact-canvas.tsx:~345`,
  `scene-artifact-canvas.tsx`, `chat-surface.tsx:~565`), signal
  (`chat.threadBusy && chat.designLegOpen`; hold website veil until `designRefresh.canvasRevision`),
  copy rule from `design-leg.ts` (no ETA/percent), done-when list.
- `v2/website.html`, `v2/ad.html` previews (output pane only, no dummy chat pane).
Verified via gstack browse at 1400x900, no console errors. Frontend facts used:
React 19.2 / Next 16.2 / Tailwind v4, `motion` present but unused here, no
`bg-brand-*` utilities (brand colours are raw `var(--clue-ds-color-primitives-*)`),
`accent-700 #5C7A82` is the only teal ramp (no `secondary`).
Preview server: `python3 -m http.server 7000` from the folder (started this session).
