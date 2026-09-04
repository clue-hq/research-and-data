# Handoff — "agent is generating" motion for the output pane

For Aryan (and the agent doing the integration). Everything needed is in this
folder; nothing here has been wired into `apps/frontend/` yet. Founder-approved
direction (2026-09-04): keep the Option-1 "Assembly" aesthetic, apply motion to
the **whole output pane**, brand colours only (no blue).

## What ships

| File | What it is |
|---|---|
| `generating.css` | The whole motion kit. Plain CSS, class-prefixed `clue-gen-*`, reads design-system tokens with hex fallbacks, has a `prefers-reduced-motion` block. Import once where the pane is composed. |
| `clue-mark.tsx` | `ClueMark` — the production mark as three `<path>`s (order matters; the CSS animates by `:nth-child`). |
| `generating-glow.tsx` | `GeneratingGlow` — perimeter haze around the pane. Decorative, `pointer-events: none`. |
| `website-generating-veil.tsx` | `WebsiteGeneratingVeil` — blur + mark assembly + title/hint. For web documents. |
| `ad-designing-lock.tsx` | `AdDesigningLock` — transparent input shield + frosted "Currently designing. Please wait to edit." pill. For scene / ad documents. |
| `index.ts` | Barrel. |
| `../v2/website.html`, `../v2/ad.html` | Browser previews that use this exact CSS. Open them to see the target. |

Suggested home: `apps/frontend/src/features/design-editor/components/generating/`
(copy the folder, keep `generating.css` next to the TSX, add `import "./generating.css"`
in the file that mounts the pane). The components import `cn` from `@/lib/utils`,
match the house style (named exports, `data-*` state, no default exports), and
use no runtime dependency — no `motion/react` needed.

## Two behaviours, one rule each

**Website (web document).** The page cannot stream, so the pane stays blurred
until the page exists. Mount `GeneratingGlow` + `WebsiteGeneratingVeil` over the
pane. The veil uses `backdrop-filter`, so whatever is underneath (previous
render, empty state, the current "Loading preview…" frame) is blurred without
touching it. If the underlying render is an iframe and `backdrop-filter` proves
unreliable on some target browser, add `filter: blur(14px)` to the canvas while
active instead; the veil still works.

**Ad (scene document).** The artwork is visible and updates live, so never blur
it. Mount `GeneratingGlow` + `AdDesigningLock`. The lock shields pointer input
on the canvas surface and shows the pill. It does **not** replace the existing
`sceneGestureDisabled` / `inspectorDisabled` plumbing (fed from
`chat.threadBusy` in `chat-surface.tsx`); keep both so the inspector, keyboard
shortcuts, and toolbar are blocked as well.

## Where to mount

- Pane container: `src/features/chat-shell/components/artifact-stage.tsx` (`ArtifactStage`).
  Give the stage element `position: relative` (or the `.clue-gen-host` class) and
  render `<GeneratingGlow active={busy} />` as its last child so the glow wraps
  tabs-free canvas area. If the tabs/header must stay outside the glow, mount it
  on the canvas wrapper one level down instead.
- Website canvas: `src/features/design-editor/components/web-artifact-canvas.tsx`.
  The loading branch around line 345 renders `Loading preview…`; render
  `<WebsiteGeneratingVeil active={generating} />` over the canvas root instead
  of (or on top of) that frame. The comment near line 58 already anticipates
  the "Generating your website…" copy.
- Ad canvas: `src/features/design-editor/components/scene-artifact-canvas.tsx`
  (`SceneArtifactCanvas`). Render `<AdDesigningLock active={generating} />` as a
  sibling of the canvas element inside its positioned wrapper.
- Chat-split mount: `src/features/chat-shell/components/chat-surface.tsx` renders
  `ArtifactStage` (~line 565) and already knows `chat.threadBusy` and
  `chat.designLegOpen`; thread a single `generating` boolean down from there.

## The signal

From `useProjectChatController` (`src/features/projects/hooks/use-project-chat-controller.ts`):

```ts
const generating = chat.threadBusy && chat.designLegOpen;
```

- Turns on at `leg.opened` / `turn.started`.
- Turns off on a terminal turn frame (`turn.completed | failed | cancelled | awaiting_input`);
  for the website, prefer to hold the veil until `designRefresh.canvasRevision`
  bumps so the blur never lifts onto a stale page.
- The standalone artifact route (`editor-surface.tsx`) has no turn stream today;
  keep `active` a prop and default it to `false` there until a document-scoped
  busy signal exists (comments at `editor-surface.tsx:190,248` describe the gap).

## Copy rules

- Website title default: "Building your landing page". Hint is optional and
  must follow the founder rule in `design-leg.ts`: no percentage, no ETA, no
  countdown. `DESIGN_GENERATION_WAIT_NOTICE` is the sanctioned hint if one is wanted.
- Ad pill default: "Currently designing. Please wait to edit." Keep it one line.

## Accessibility and motion

- Both overlays are `role="status"` + `aria-live="polite"`; `aria-hidden` flips with `active`.
- The lock sets `cursor: progress` so the block reads as intentional, not broken.
- `prefers-reduced-motion` removes rotation, assembly and shimmer but keeps the states.
- Glow width, colours, and timing are CSS custom properties / keyframes at the
  top of `generating.css`; tune there, not in TSX.

## Done when

1. Ask for a landing page in a project chat: the pane blurs, mark assembles,
   glow breathes; on the canvas revision that carries the page, veil and glow
   fade and the page is sharp. No flash of the old page.
2. Ask for an ad change: artwork stays visible and updates; pill + glow on;
   clicking a node does nothing; inspector disabled; both clear on the terminal frame.
3. `npm run design-system:build && npm run lint && npm run build` green.
4. With "Reduce motion" on in macOS, both states render static but readable.
