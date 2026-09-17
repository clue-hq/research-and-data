# Output-pane loading animation — exploration (2026-09-04)

## v3 — depth at the edges (third pass, same day)

Founder review of v2: the glow was scattered and flat, the chip too round.
Comet's frame is three stacked layers (crisp line on the edge, tight bloom,
wide haze) with the bright part travelling the perimeter, over a slightly
recessed edge. v3 rebuilds `GeneratingGlow` that way with two variants,
`aurora` (two slow light-bands) and `beam` (one fast bright head), squares the
chip to the frontend's 8px radius with `frost` and `ink` appearances, and adds
an `ink` tone for the website veil. Previews: `v3/website.html`, `v3/ad.html`
(A/B switch in the control bar; `?v=a` / `?v=b`).

## v2 — what ships (founder review, later the same day)

Founder kept Option 1's aesthetic and asked for two production animations that
cover the **entire output pane**, in brand colours (not Comet's blue):

- **Website**: the page cannot stream, so the pane stays blurred until it
  exists. `v2/website.html`.
- **Ad**: the artwork is visible and updates live, so never blur it; lock input
  and show a Moda-style pill, "Currently designing. Please wait to edit."
  `v2/ad.html`.
- Both get a Comet-style perimeter glow (sage / cream / slate-teal, slow
  rotation, breathe).

The deliverable for Aryan is `handoff/`: one `generating.css` (the only source
of the motion; the previews link the same file), four React components
(`ClueMark`, `GeneratingGlow`, `WebsiteGeneratingVeil`, `AdDesigningLock`) in
the frontend's house style, and `HANDOFF.md` with mount points, the busy
signal, copy rules, and a done-when checklist. References: `reference/` now
also holds frames from the Comet + Moda recordings.

## v1 — the original four options

Self-contained folder. Nothing here touches `apps/frontend/`; it is a set of
browser-openable mockups for deciding what the right-hand output pane should do
while the model is generating an artifact.

**Open `index.html` in a browser.** Everything is linked from there. No build
step, no server; the Satoshi font files are copied in so the pages look right
offline.

## What the Play recording does (frame by frame)

5.6 s clip, 52 fps, right-hand output pane only:

1. t≈0.0 s — the previous page snaps to a blurred (~12 px), desaturated,
   slightly scaled ghost. Sidebar and toolbar stay sharp.
2. t≈0.2–0.9 s — four 3D "toy" shapes pop in one after another, ~0.2 s apart
   (blue flower, purple cylinder, green cushion square, yellow star), each with
   an overshoot bounce.
3. t≈0.9–4.5 s — each shape idles with its own motion (rock, bob, tilt,
   pulse). "Loading preview…" sits beneath with a left-to-right text shimmer.
4. t≈4.6–5.6 s — the blur clears and the new page fades in; the shapes fade out.

Frames are in `reference/`, including a 6 fps strip of the pop-in
(`play-glyph-stagger-6fps.png`).

## The four options

| # | Name | Idea | Progress-aware | Closest to Play |
|---|------|------|:--:|:--:|
| 1 | Assembly | The three pieces of the Clue mark drift in, lock, breathe, ease apart, repeat | no | — |
| 2 | Segments | Frosted ghost + four brand segments popping in, each with its own idle motion | no | yes |
| 3 | Blueprint | Wireframe of the artifact draws in and fills per generation step; step list + mark spinner | yes | — |
| 4 | Develop | The artifact sharpens like a developing photo, one notch per step; crescent progress arc | yes | — |

All four share `animations/shell.css`, which mimics today's screen (chat pane
left, tabs + toolbar + centred card right) and the hand-off transition: blur
clears, the finished artifact eases in. Press **Finish generation** to see it.

Recommendation: 3 or 4 if generation steps are exposed by the backend as
events (they are, on the project run stream), because a marketer waiting 30–60 s
wants to know *what* is happening, not just *that* something is. 1 is the
strongest pure brand moment and works for short waits. 2 proves the Play shape
in Clue's colours but is the least distinctive.

## Logo files (`logos/`)

Five standalone SVGs built from the current production geometry, with a
gallery at `logos/index.html`:

- `01-clue-mark-cream-on-ink.svg` — app-icon tile
- `02-clue-mark-olive.svg` — mark alone, for light surfaces
- `03-clue-mark-cream.svg` — mark alone, for dark surfaces
- `04-clue-lockup-olive.svg` — mark + "Clue" letters
- `05-clue-lockup-cream-on-ink.svg` — lockup on an ink tile

Sources on this machine: `apps/frontend/public/icons/clue-mark.svg`,
`~/Documents/clue-website/public/favicon.svg` (largest clean mark),
`~/Documents/clue-website/public/assets/clue-wordmark.svg` (lockup).
Beware `~/Downloads/Clue Design System/` — it is an older oxblood-coloured
exploration that contradicts production.

## Brand tokens used

From `apps/frontend/packages/design-system/generated/tokens.css`: ink `#161814`,
olive-950 `#33372E`, olive-800 `#44483F` (the wordmark colour), olive-900
`#646B5C`, sage-600 `#A6AD9D`, sage-500 `#BCC4B3`, brand-200 `#E4EADC`,
brand-100 `#EEF2E9`, brand-50 `#F8FAF6`, cream `#F8F5DC`, slate-teal-700
`#5C7A82`. Font: Satoshi 400/500.
