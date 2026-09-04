# Handover — "agent is generating" motion for the output pane

**For:** Aryan (and the agent doing the integration).
**Approved by:** Shashank, 2026-09-04, after four review rounds.
**Branch:** `handoff/output-pane-generating-motion` on `clue-hq/research-and-data`.
This branch is an orphan: it contains only this folder, nothing else from the monorepo.

Open `preview/website.html` and `preview/ad.html` in a browser first. That is the
target. Both previews use the exact same stylesheet the components use, so what
you see is what ships.

## What it is

Two behaviours for the right-hand output pane while an agent is working, both
in brand colours, both with a thin light frame at the pane's edges:

- **Website** (web document). The page cannot stream, so the whole pane blurs
  until the page exists. The Clue mark assembles, breathes, and re-assembles in
  the centre with one line of copy.
- **Ad** (scene document). The artwork stays visible and keeps updating live.
  A transparent shield swallows pointer input and a small chip reads
  "Agent is designing. Please wait." with the Clue mark as a spinner.

The frame is four stacked layers masked to the edges (a soft haze, a tight
bloom, a 2px line, a hairline rim). Two bands of sage, cream, white, and
slate-teal drift around the perimeter on an 11 s loop. The centre stays clean.

## Files

| Path | What |
|---|---|
| `components/generating.css` | The whole motion. Plain CSS, class prefix `clue-gen-*`, reads design-system tokens with hex fallbacks, `prefers-reduced-motion` block. Import once. |
| `components/clue-mark.tsx` | `ClueMark` — the production mark as three `<path>`s. Order matters; the CSS animates by `:nth-child`. |
| `components/generating-glow.tsx` | `GeneratingGlow` — the edge frame. `active: boolean`. Decorative, `pointer-events: none`. |
| `components/website-generating-veil.tsx` | `WebsiteGeneratingVeil` — blur + mark + `title` / `hint`. `active: boolean`. |
| `components/ad-designing-lock.tsx` | `AdDesigningLock` — input shield + chip. `active: boolean`, `label`, `placement`. |
| `components/index.ts` | Barrel export. |
| `preview/` | The two browser previews plus their chrome and the Satoshi font files. Not for production. |

## Copy-paste steps

1. Fetch the branch and copy the components folder into the frontend:

   ```bash
   git fetch origin handoff/output-pane-generating-motion
   git checkout origin/handoff/output-pane-generating-motion -- components
   mkdir -p apps/frontend/src/features/design-editor/components/generating
   git mv components/* apps/frontend/src/features/design-editor/components/generating/
   ```

   Or without git: download the branch as a zip from GitHub and copy `components/`
   to `apps/frontend/src/features/design-editor/components/generating/`.

2. The components import `cn` from `@/lib/utils` (already in the frontend) and
   nothing else. No `motion/react`, no new dependency.

3. Import the stylesheet once in the file that composes the output pane:

   ```ts
   import "./generating/generating.css";
   ```

4. Give the pane element a positioning context. Either add the `clue-gen-host`
   class or make sure it already has `position: relative`. All three components
   are `position: absolute; inset: 0` inside it.

5. Mount:

   ```tsx
   // artifact-stage.tsx (or the canvas wrapper one level down)
   <div className="clue-gen-host">
     {/* existing canvas */}
     {kind === "web"   && <WebsiteGeneratingVeil active={generating} />}
     {kind === "scene" && <AdDesigningLock active={generating} />}
     <GeneratingGlow active={generating} />
   </div>
   ```

## Where in the app

- Pane container: `src/features/chat-shell/components/artifact-stage.tsx` (`ArtifactStage`).
- Website canvas: `src/features/design-editor/components/web-artifact-canvas.tsx`.
  Its loading branch (around line 345) renders "Loading preview…"; the veil
  replaces or sits on top of that frame. The comment near line 58 already
  anticipates the "Generating your website…" copy.
- Ad canvas: `src/features/design-editor/components/scene-artifact-canvas.tsx`
  (`SceneArtifactCanvas`). The lock is a sibling of the canvas element inside
  its positioned wrapper. Keep the existing `sceneGestureDisabled` /
  `inspectorDisabled` plumbing (fed from `chat.threadBusy` in
  `chat-surface.tsx`) so inspector, keyboard, and toolbar are blocked too; the
  lock only covers the canvas surface.
- Chat-split mount: `src/features/chat-shell/components/chat-surface.tsx`
  renders `ArtifactStage` (~line 565) and already knows `chat.threadBusy` and
  `chat.designLegOpen`. Thread one `generating` boolean down from there.

## The signal

From `useProjectChatController` (`src/features/projects/hooks/use-project-chat-controller.ts`):

```ts
const generating = chat.threadBusy && chat.designLegOpen;
```

- On at `leg.opened` / `turn.started`.
- Off on a terminal turn frame (`turn.completed | failed | cancelled | awaiting_input`).
  For the website, hold the veil until `designRefresh.canvasRevision` bumps so
  the blur never lifts onto a stale page.
- The standalone artifact route (`editor-surface.tsx`) has no turn stream yet;
  keep `active` a prop and default it to `false` there (see the comments at
  `editor-surface.tsx:190,248`).

## Copy rules

- Website title default: "Building your landing page". The hint is optional and
  must follow the rule in `design-leg.ts`: no percentage, no ETA, no countdown.
  `DESIGN_GENERATION_WAIT_NOTICE` is the sanctioned hint if one is wanted.
- Ad chip default: "Agent is designing. Please wait." One line.

## Things worth knowing

- The sweep animates a registered custom property (`@property --clue-gen-angle`)
  so the gradient stops travel along the rectangle's edges. Chromium, Safari
  16.4+, Firefox 128+; older browsers show a static frame.
- The edge masks are declared on the child layers, not the parent, on purpose.
  `--reach` is per layer, and a custom property resolves where it is declared.
- Stacking inside the host: veil 6 < glow 7 < lock 8.
- Chip radius reads `--radius-lg` (8px in `globals.css`) with an 8px fallback.
- Tuning lives at the top of `generating.css`: `--reach` per layer sets how far
  the light spills in, the conic stops set the colours, `11s` sets the pace.
- Both overlays are `role="status"` + `aria-live="polite"`; the lock sets
  `cursor: progress`; reduced motion removes movement but keeps the states.

## Done when

1. Ask for a landing page in a project chat: the pane blurs, the mark assembles,
   the frame lights; on the canvas revision that carries the page, veil and
   frame fade and the page is sharp. No flash of the old page.
2. Ask for an ad change: artwork stays visible and updates; chip and frame on;
   clicking a node does nothing; inspector disabled; both clear on the terminal frame.
3. `npm run design-system:build && npm run lint && npm run build` green.
4. With "Reduce motion" on in macOS, both states render static but readable.
