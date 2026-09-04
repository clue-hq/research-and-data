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
