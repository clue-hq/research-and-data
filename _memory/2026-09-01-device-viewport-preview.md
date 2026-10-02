# 2026-09-01 — Device viewport preview (Desktop/Tablet/Mobile) made real in the platform shell

## What changed
The artifact header's device dropdown (web artifacts only) was dummy state — chosen device
never left `use-artifact-toolbar-controller`. It now drives the web canvas viewport width:

- `apps/frontend/src/features/chat-shell/hooks/use-artifact-toolbar-controller.ts` — device is
  liftable (controlled `device` + `onDeviceChange`), mirroring the AD2.8 zoom lift; local state
  survives as the uncontrolled fallback.
- `.../components/artifact-header.tsx` — threads the two new props; controller value
  destructured as `activeDevice` (prop/name collision was a real build failure).
- `.../components/artifact-stage.tsx` — owns `useState<ArtifactPreviewDevice>("Desktop")`
  (per-stage-session, nothing persisted; added "use client"); passes it to the header and maps
  it to a class on the `.webCanvas` wrapper. Both routes (chat-surface + editor-surface) render
  ArtifactStage, so both got the feature.
- `.../components/chat-shell.module.css` — `.webCanvasTablet` (768px) / `.webCanvasMobile`
  (375px): centered via cross-axis auto margins (collapse to 0 + scroll on overflow — the
  source shell's own comment), subtle border/radius/shadow from existing tokens, width
  transition 200ms (px↔px animates; the fluid desktop leg snaps).

## Key discovery (founder's hunt confirmed)
The widths are NOT invented: lumen-web's authoring grammar (LUMW0203, `classes.rs`) pins
exactly three viewport layers — 375px base, 768px `md:`, 1440px `lg:` — and the design agent's
review loop renders previews at those 3 widths. The design dev shell (`WebEditorApp.tsx`
`WidthMode` chips + `web.css .web-preview-holder`) already did client-side width pinning;
it was never ported to the platform shell. This change is that port. Desktop = fluid
full-bleed (matches prior behavior), NOT a 1440 pin.

## Verification
- `npm run design-system:build && npm run lint && npm run build` green; `npm test` 2044/2044.
- Live (browse daemon, dev stack 3020, OpenAI/Stripe dry-run artifact): Mobile → canvas
  exactly 375px centered (87px gaps), Tablet → exactly 768px centered, Desktop → full-bleed
  (1349px stage). Real breakpoints engage (hero stacks, header collapses on mobile).
- Dev login walk: sign-in → email → Clerk test code 424242 → select-workspace →
  /projects/{id}/gallery → artifact. Note: sidebar + projects-region "Untitled project"
  buttons share an accessible name — browse @ref clicks fail ambiguous; use JS click.

## Not done / out of scope
- `subsystems/clue-design/apps/editor` has its own separate chrome (already functional
  there) — untouched.
- Device choice is presentation-only; no persistence, no per-artifact memory.
