# Research status card visual preview — 2026-09-13

- Founder requested preview-first visual polish of the pinned multi-account research card.
  Functional behavior is accepted; production implementation waits for design feedback.
- Semarang checkout on `visual-polish`; actual target is `research-progress-card.tsx` beside
  the chat composer, not the older transcript `chat-research-task.tsx` component.
- Created ignored, standalone `.runtime/research-card-preview/` with build/serve scripts,
  React entry, CSS and README. It imports the real card, copy formatters and generated tokens;
  scoped CSS overrides provide Proposed vs Current. Data is synthetic and transport-free.
- Proposed: 14/20 medium title, 13/18 supporting text, 4px badge corners, 0.5px border,
  8px card corners matching the app composer, 16px padding/icon, 12px gaps and 4px progress.
  Colors/type/border/badge use published tokens; 8px is the app base radius, and the other
  component geometry choices still need ratification. Header grid handles narrow panes.
- Running/completed/attention, three widths, long names and next-activity controls are available.
  Main component, copy semantics, backend, environment files and existing servers unchanged.
- Preview served on unused loopback port 3046; existing 3040/3045/8070 listeners left running.
  Initial bind failed with sandbox EPERM; reviewed escalation then started successfully
  (exec session 63214). Initial build could not resolve absolute font URLs; marked /fonts/*
  external so the explicit static server allowlist supplies them. Build then passed.
- Browser verified current/proposed, all status states, activity switching, completion 100%,
  loaded icons, and empty warning/error logs. At 320px, no card/chat/page horizontal overflow,
  attention badge/title do not overlap, and long status text uses a contained ellipsis.
  A getByLabel exact selector failed; role-based combobox selectors worked after DOM inspection.
- User-facing tab at http://localhost:3046 is retained. Final QA moved to a separate background
  tab after the user began inspecting the preview. No live research was launched.
- Next: collect founder visual edits in this demo, finalize design, then implement the approved
  CSS/token changes in the production component. MDXEditor and other Lane 2 work not touched.

## Approved implementation

- Founder clarified that the oversized-text annotations referred to Current, approved Proposed
  without further reductions, and authorized implementation in the main repo.
- Updated only `research-progress-card.module.css` and the component's icon size (24 to 16).
  Title and account count use text-default (14/20), supporting text uses text-sm (13/18).
  Semantic colors, grid border and badge radius consume published tokens; card uses app radius.
  Approved spacing, header grid, slimmer progress bar and existing ellipsis are preserved.
  No data contracts, polling, counts, status semantics or research execution changed.
- Updated the ignored review page to compare Implemented (actual component, no preview CSS
  overrides) with Approved preview. Defaults to Implemented to avoid the earlier ambiguity.
- Gates: design-system build, ESLint and production Next build passed. ESLint reports the
  same two existing unused-function warnings in canvasOperations.ts. Nine focused research-card,
  formatter and design-token tests passed; git diff --check passed. No new tests for this CSS edit.
- Browser measurements matched the approved override exactly at full width: 155px card height,
  8px radius, 0.5px border, 16px padding/icon, 12px gaps, 14px title/count and 13px activity text.
  Verified completed at split width and attention with long text at 320px: no horizontal overflow,
  no title/badge overlap, contained single-line ellipsis; no preview console warnings/errors.
- Main dev server recompiled successfully and answered the chat route with HTTP 200, but the
  route displays the workspace-session recovery screen. Initial browser navigation timed out;
  reattached to the existing tab and verified the session error. Live research-run verification
  remains unavailable until the workspace session works; no paid research or data edits attempted.
- Environment files and other running servers were untouched. The implementation review remains
  at http://localhost:3046. Changes are a local CSS checkpoint; no remote publication requested.
