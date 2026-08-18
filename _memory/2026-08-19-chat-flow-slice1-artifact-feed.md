# 2026-08-19 — Chat-flow editor integration, Slice 1: the chats route serves the real gallery feed

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md` §4 Slice 1. Start gate
(lane C merged) verified: `44a24088` records the merge; suite was 752/752 at merge time.

## What shipped

- **Shared helpers extracted** (the artifact page's private functions, now two files in
  `features/design-editor/data/`):
  - `gallery-feed.ts` — `loadGalleryFeed(repository, projectId) → {cards, documentIds}`
    (the GalleryFeed shape). Deliberately free of `server-only` imports so `tsx --test`
    can run it; the repository is injected.
  - `artifact.repository.server.ts` — `backendDesignArtifactRepository()` (the
    `fetchAuthenticatedClueBackend`-backed W2.1 construction; transitively server-only).
  Split rationale: one testable pure loader + one server-only builder — a single file
  would make the loader untestable under the repo's node:test runner (`server-only`
  throws outside RSC).
- **Artifact page** (`artifacts/[artifactId]/page.tsx`): rewired onto the shared helpers;
  behavior identical (same refusal postures, same whole-feed + route-artifact
  `documentIds` merge).
- **Chats page** (`chats/[chatId]/page.tsx`): `Promise.all(getProjectWorkspace,
  loadGalleryFeed)`; passes `artifacts={feed.cards}` `documentIds={feed.documentIds}` to
  `ProjectWorkspaceShell`.
- **Threading:** `ProjectWorkspaceShell` → `LoadedProjectWorkspace` → `ChatSurface`, both
  props optional (the legacy `/projects/{id}` absorber passes neither — its gallery keeps
  the honest empty state; its client-side canonicalization `router.replace`s to the chats
  route, whose server component then fetches the feed). `ChatSurface` renders
  `ArtifactStage artifacts={artifacts ?? []}` (was `workspace.artifacts`);
  `documentIds` is DECLARED in ChatSurface's prop type but not destructured — slice 3
  consumes it (kept out of the destructuring so no-unused-vars stays clean).
- `workspace.artifacts` (`z.tuple([])`) untouched, per the plan.

## Tests

`gallery-feed.test.ts` (5): cards + map (map direction pinned with id ≠ documentId
fixtures), wire-shape (ProjectArtifactSchema + Z-form timestamps), empty-project vs
refusal distinction, list-read failure → empty feed, unmappable timestamp → empty feed.

## Verification

- Gates: frontend suite **757/757**, lint clean, design-system:build ✓, `next build` ✓.
- **Browser (authenticated 3030 stack):** chat screen
  `/projects/prj_79aa…/chats/thr_4ef1f65…` → open artifact panel → Gallery shows the REAL
  Insight Health homepage card ("1 artifacts", "Last edited yesterday") → card click
  opens the tab (real title; shell data attrs show
  `artifactId=doc_31126145a0aa4753920629ae323a301b, kind=web, editing=false`); canvas
  EMPTY as specified (mount is slice 3). Artifact route smoked unchanged: real render,
  Edit docks the inspector (real layers + canvas schema), Edit off restores.
- Commit: `feat(part4): chats-route artifact rail serves the real gallery feed`.

## Ops notes (this session)

- 8030 was down (platform API); relaunched per the recorded recipe (shell env
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` + 3030). NOTE: a `nohup … &` inside a completed
  agent-shell call gets REAPED — launch long-running servers as a persistent background
  shell task instead. 3030 (next dev, istanbul) and 8010 (design API) were already up.
- Browser session had expired → full re-login (sign-in-email → 424242 → select-workspace).
  `/session/establish` renders blank and doesn't auto-advance in the automated browser;
  navigating straight to `/select-workspace` after verify works.
- The artifact rail's entry transition briefly reports gallery cards as `opacity: 0` to
  the click tool right after opening the panel — retry after the transition settles.

## Next

Slice 2 — extract `useWebEditingSession` from `EditorSurface`'s hooks region (pure
refactor, zero test edits; must absorb lane C's rich-text/custom-component session state
verbatim).
