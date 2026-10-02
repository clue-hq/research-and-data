# 2026-09-03 — Agent-working chip (visible form of the scene editor lock)

Founder request 2026-09-03 with three reference screenshots: while the design agent works, a
persistent chip at the top edge of the editor area showing a pulsing dotted grid and shimmering
"Designing. Please wait to edit.", so the user can see the document is not theirs to edit yet.

## What shipped (commit e5e2ed07a, plan `docs/superpowers/plans/2026-09-03-agent-working-chip.md`)
- `chat-shell/components/agent-working-chip.tsx` + `.logic.ts`: presentational chip
  (`role="status"`, `aria-live="polite"`, decorative 3×3 dot grid, label) and the visibility rule
  `shouldShowAgentWorkingChip({editDisabled, hasScene})`.
- `chat-shell.module.css`: `.sceneStage` gains `position: relative`; chip pinned top-left (12 px),
  `pointer-events: none`, z-index 4; dot pulse + text shimmer as CSS keyframes; static under
  `prefers-reduced-motion`. Tokens from the file's own pill rules (`--chat-shell-neutral`,
  `--chat-shell-border`, `--clue-ds-shadow-card-subtle`, `--chat-shell-content`,
  `--chat-shell-subtle`), no hex.
- `artifact-stage.tsx`: renders the chip as the first child of `.sceneStage` when the stage's
  existing `editDisabled` prop (rung A's `agentRunLock.locked`, passed by `chat-surface.tsx`) is
  true and a document is active. No new state or data flow.
- Searched libraries first (prompt-kit / shadcn.io AI `Shimmer`, animbits, ldrs `grid`); chose
  zero-dependency CSS because `motion` already exists and the effect is ~40 lines.

## Rulings
- R1 copy: the chip says the screenshot's words; the Edit pill tooltip keeps rung A's ratified
  lock sentence. R2 position: top-left (founder allowed top-center). R3 scope: scene editor only.
- Test-file mechanics (implementer, accepted): `.test.ts` + `createElement` so `npm test`'s
  `*.test.ts` glob finds it; the CSS-module import is stubbed via `Module._extensions[".css"]`
  because node:test has no CSS loader.

## Verified
- 3/3 chip tests; chat-shell suite 140/140; frontend gate green (2 pre-existing lint warnings).
- LIVE (controller, gstack browse): sent "Make the headline one size larger…" on the Apollo
  thread; with the run in flight, the thread route's artifact rail showed the chip top-left of
  the stage, dots pulsing, sweep mid-label (`/tmp/apollo-chip-rail2.png`); the a11y tree lists
  `[status]: Designing. Please wait to edit.`. When the run released (status left `running`), the
  chip was gone on the next snapshot and the only status was "Design is ready for your next
  message." (`/tmp/apollo-chip-cleared.png`).

## Finding (rung A gap, NOT the chip's): the standalone artifact route has no lock
`/projects/{p}/artifacts/{id}` renders `ArtifactStage` through `editor-surface.tsx`, which passes
no `editDisabled` — so during a run that page shows a live Edit pill and no chip; only the
backend's 409s refuse writes there. The lock is derived in `chat-surface.tsx` from the thread
stream + durable `design_leg_state`, which the editor surface does not have. Fix shape: seed the
lock on the editor surface from the document's origin thread's durable leg state (the
`ThreadWire.speaker.design_leg_state` floor rung A already reads), or route the standalone page
through the same controller. Founder decision pending.
