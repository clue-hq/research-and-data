# 2026-08-19 — genweb F2(b): the leg-born artifact opens itself

Branch `integration/frontend-design-part-iv-v2`. Frontend only (`apps/frontend/`).
Founder ruling F2 **(b)**, 2026-08-19, supersedes option (a) for v1: when a design leg
births its web document, the artifact tab opens by itself next to the Gallery.

## What shipped

- `src/features/chat-shell/model/artifact-auto-open.ts` — the whole decision, pure:
  `artifactToAutoOpen({activeThreadId, artifacts, knownArtifactIds})` → an open-artifact
  descriptor or `null`.
- `src/features/chat-shell/model/artifact-auto-open.test.ts` — 11 cases under `tsx --test`.
- `src/features/chat-shell/components/chat-surface.tsx` — transport only: a mount-snapshot
  ref + one effect that calls the existing `shell.openArtifact`.
- `src/features/projects/model/design-leg.ts` — docstring corrected off option (a).

Commits: `730e3e40` (code), plus the docs commit carrying this note and the report.

## The design decision that matters

`leg.opened` carries ONLY `{leg_id}` (`design_leg_tools.py::_emit_leg_lifecycle`). It
names no document, so the frame cannot say *what* to open. What it does do (slice 3) is
bump `designRefresh.feedRevision` → `router.refresh()` → the chats page re-runs
`loadGalleryFeed` and hands down fresh `artifacts` props. So the **feed is the trigger,
not the frame**: snapshot the feed's artifact ids at mount; auto-open an id that is new
since that snapshot AND whose `originThreadId` is the active thread.

Why not the frame: on a cold load the replayed backlog re-fires `leg.opened` and one
redundant `router.refresh()` — a frame-keyed rule would re-open the tab on every page load
of a design thread. Verified in the browser that the snapshot rule does not.

`leg.reopened` is handled for free: a reopen births no document, so its feed refresh
carries no id the page has not already banked.

## Rules encoded

- No active thread → never. Different `originThreadId` → never. In the mount snapshot →
  never.
- Everything a feed delivery carries is banked as known *before* acting, so a document
  opens at most once and a tab the user then closes stays closed.
- Several new at once → the newest `createdAt` wins; no usable timestamp ranks oldest
  (still opens when it is the only candidate); an exact tie is broken by feed order, first
  wins (the feed is served newest-updated-first). Only ONE opens.
- Kind derivation reuses the gallery's own rule (`website` → web, else ad); the open path
  is the very same `shell.openArtifact` the gallery card's click uses, so tab creation,
  activation and the R6 dock choreography are identical either way.

## Interactions checked

- The mount snapshot is taken on the first *commit*, not during render (no render-phase
  side effects). Same set either way: the chats page awaits `loadGalleryFeed` server-side,
  so the first client render already holds the complete feed.
- `ProjectWorkspaceShell`'s `workspaceRemountKey` includes `threadId`, so a thread switch
  remounts and re-snapshots — switching to a thread that already has documents opens
  nothing.
- The URL write-back effect does not fight it: the auto-open sets `surface: "artifact"`,
  the write-back replaces `?surface=web`, that re-render delivers a new `artifacts`
  identity, the effect re-runs and finds everything known → no loop. Its own loop guard
  (replace only on a real difference) still holds.
- A stable module-level `NO_ARTIFACTS` replaces the two `artifacts ?? []` literals, so a
  feed-less mount does not hand the effect a fresh array identity every render.

## Verification

- `npm test` 868/868 (was 857 before the 11 new cases); `npm run design-system:build`,
  `npm run lint`, `npm run build` all clean.
- Browser (Playwright MCP, dev stack on :3030, no server restarted):
  - cold load of the founder's design thread `thr_2a1badf9…` (its `leg.opened` replays) →
    tablist is `Gallery [selected]` only. No re-open.
  - new thread `thr_24f6a729…` in `prj_gallerynegcheck0000000000000001`, one landing-page
    ask (delegation turn only — no generation started) → `doc_2ab3f137…` born 16:12:56 and
    its tab "Insight Health Neurosurgery Analytics Launch" opened by itself next to
    Gallery, selected, with the artifact header/Edit/Share. Canvas is the empty v0
    document, as intended (it fills when the generation turn commits).
  - reload of that page → tab does not re-open; the rail falls back to the Gallery, whose
    feed now carries the new card.
  - Screenshots `.playwright-mcp/f2b-{cold-load-no-autoopen,auto-opened-tab,reload-no-reopen}.png`.
    No new console errors.

## Open notes / caveats

- `shell.openArtifact` sets `editing: false`. If a birth lands while the user is editing a
  *different* artifact in the same thread, they are moved to the new tab and out of edit
  mode. Inherent to the ruling (the new tab must become active); flagged, not fixed.
- A deep link still restores pane state, not the open tab (pre-existing, R2). So a URL left
  at `?surface=web` after an auto-open reloads onto the Gallery, not onto the tab. Honest,
  but if the founder wants the tab to survive a reload, artifact identity has to enter the
  shared URL vocabulary — a separate ruling.
- No component-level test: the repo's runner is DOM-less (`find src -name '*.test.ts'`),
  so the rule is proven in the model and consumed, never restated, in the component — the
  same posture as `chat-dock`.
