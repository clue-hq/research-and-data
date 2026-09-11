# Brand Context polish — 2026-09-12

Branch `brand-context-polish`, base `bffccc082`. Founder authorized the four B1–B4
items in `docs/superpowers/plans/2026-09-10-arv2-frontend-polish-backlog.md`:
uniform Knowledge rows and one-pass hover scrolling; library-only Markdown
rendering; actual extracted-font samples; full-size proportional asset previews.
Other frontend defects are deferred. Remove the custom Markdown parser and inline
renderer completely; use react-markdown + remark-gfm. The current Knowledge view
is read-only; persistent editing is outside this rendering repair.

Initial inspection: the font wire schema drops `faces` (asset IDs / source URLs),
the typeface mapper retains names only, and the asset dialog caps images at 280px.
Existing Markdown tests assert the removed parser's implementation; update those
callers when deleting it. Validation will use the frontend release gate and a
separate local browser preview without starting research or touching sibling stacks.

## Implementation and verification

- B1: fixed 32 px rows / 16 px icons; CSS container-relative one-pass hover/focus
  scrolling, reduced-motion support, full title tooltip/accessibility.
- B2: deleted `parseKnowledgeMarkdown`, `MarkdownBlock`, `renderInline`, and the
  controller's parsed-block state. Library renders original document bytes; CSS
  styles all heading levels, tables, lists, quotes, links, code and GFM output.
  Updated existing Design.md projection tests to consume the library.
- B3: preserved recorded font faces through the frontend wire/model mapper;
  stored asset IDs prefer authenticated BFF bytes, else HTTP(S) source URLs.
  Namespaced kit/version families prevent collisions. CSS string escaping protects
  declarations; invalid face rows are individually omitted. No backend change.
- B4: removed the image's 280 px cap and fixture exception; proportional contain
  fills the preview; existing desktop/stacked-mobile description layout preserved.
- 89 focused tests pass. Design-system build / lint / production build pass;
  existing canvasOperations.ts unused `snapPosition`/`snapExtent` warnings remain.
- Isolated Next preview :3045 and agent-browser session `semarang-brand-polish`:
  fixed row/icon measurements, long-title travel -508 px then return (one iteration),
  reduced-motion animation none, semantic GFM elements, test font status loaded,
  desktop preview 727.6 x 567 px and mobile details below at 390 x 844. Normal
  `/brand-context?section=knowledge` and `/` loaded without an error overlay.
  Screenshots `.context/brand-context-polish-2026-09-12/`. Synthetic test font used
  existing local Satoshi bytes through a recorded URL; real tenant font/CDN reachability
  not exercised. Temporary proof route removed; preview and browser stopped.

## Execution pitfalls

- npm's sandbox could not resolve registry.npmjs.org (ENOTFOUND); terminated retry
  loop and installed the two authorized libraries with network escalation.
- tsx CLI IPC socket hit sandbox EPERM; `node --import tsx --test` ran successfully.
- Initial lint caught two createElement children-prop usages in changed tests;
  moved children to the third argument and reran successfully.
- Initial fixture preview inherited CLUE_PROJECTS_API_BASE_URL and its sidebar
  requested the auth-disabled BFF. Restarted only this preview with that variable
  empty alongside CLUE_API_BASE_URL and CLUE_AUTH_ENABLED=false; error cleared.
  These were process-local settings; no env files or sibling stacks changed.

## ENG-182 follow-up — 2026-09-12

Founder supplied the Linear issue and screenshot and requested this asset-detail frontend
slice next. The issue URL was unavailable through the web tool; used the supplied screenshot
and current implementation. Prior B4 already removed the 280 px cap. This follow-up expands
usable modal size to 1440 x 960 max within the viewport, reserves a readable 280–360 px desktop
details column, wraps long asset names, and gives details their own scroll area. Mobile uses
16 px outer margins and two shrinkable rows so short screens no longer clip the detail pane.
Images remain proportional with contain, never cropped or distorted. No asset data mutations.

Browser proof used the production components with existing fixture artwork and a deliberately
long filename/description in a temporary authenticated proof route (removed afterwards). The
live Semarang workspace still has no extracted design assets; no brand extraction was launched.
- Desktop 1440 x 1000: modal 1376 x 936, preview 1014 x 934, details 360 px wide; image fills
  its preview element, contain preserves original proportions; no horizontal overflow.
- Mobile 390 x 844: modal 358 x 812, preview above details, 356 px content widths; independent
  description scroll and no horizontal overflow. Short 844 x 390 viewport also fits completely.
- Screenshots: .runtime/eng-182-desktop.png and .runtime/eng-182-mobile.png. No browser errors.

Verification cleanup: the temporary proof route was removed and the separate browser closed.
Initial cleanup commands ran from the frontend directory with root-relative paths and failed;
corrected paths immediately. The gate caught the temporary fixture import before cleanup;
removed the proof route and reran checks against the final source. No lint rule was weakened.

Final gate: lint and production build pass on the cleaned final tree (the two inherited
canvasOperations unused-function warnings remain). Prior Markdown release gate also passed
its design-system build, 92 frontend tests and 16 backend tests. Asset follow-up changes only
CSS and documentation; desktop, mobile and landscape visual checks cover the layout change.
