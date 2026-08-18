# Chat-Flow Editor Integration — Ratified Plan (the R6 mount)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans, task-by-task. **Process rule (founder, binding): Opus agents
> implement; the orchestrating session reviews every diff INLINE itself — never via a
> reviewer subagent.** TDD throughout. This doc is self-contained: every file:line fact
> below was verified 2026-08-19 against the trunk AT the lane-B merge (`8dde2199`) —
> line numbers in `web-inspector.tsx`/`editor-surface.tsx`/`apply.ts` will have drifted
> slightly; re-verify anchors before editing.

**Where it runs:** the trunk (`integration/frontend-design-part-iv-v2`), **strictly AFTER
lane C (`feature/w4-lane-c-richtext-components`) merges** — lane C is growing exactly the
`editor-surface.tsx` hooks region and `artifact-stage.tsx` prop lists this plan
restructures (§7 of the scout inventory). Do not start while lane C is unmerged. Local
commits only, never push, no AI attribution.

**Goal:** the chat screen (`/projects/{id}/chats/{chatId}`) gains the live website editor:
the artifact rail shows real artifacts and renders the working canvas; pressing **Edit**
replaces the conversation column's transcript with the inspector while **the composer
stays pinned at the bottom**; **sending a message dismisses the dock** and the
conversation returns; Edit reopens it. The artifact route keeps working unchanged.

---

## 1. Ratified rulings (do NOT re-litigate)

- **R6 (accepted for v1; founder-ratified 2026-08-18 + composer clarification 2026-08-19):**
  while `editing`, the inspector replaces the conversation column's transcript. The
  **composer remains visible and usable below the dock** (it was never inside the
  transcript — see §3.5). Recorded at `docs/superpowers/plans/2026-08-17-phase-c-chat-chrome-adoption.md`
  R6 bullet and `_memory/2026-08-17-w01-shell-lift-file-set.md` ("R6 dock ruling ratified").
- **Edit-only entry:** the dock appears ONLY via the Edit button while a specific artifact
  is open — never any other trigger.
- **Send dismisses:** a message successfully submitted to the agent closes the dock and
  restores the conversation; Edit reopens it.
- **R2 / Phase R URL vocabulary (ratified 2026-08-17, verbatim at
  `apps/frontend/docs/api-contracts/projects.md:7-30`):** pane state on the chats route is
  `?surface=` (`chat|gallery|web|ad`) + `?edit=1` + `?selection=`; the superseded
  `?artifact=` param must not be introduced. Artifact identity on the chats route is a
  runtime tab selection, not a path param.
- **Visual parity:** the dummy chat shell is baseline and ceiling. The R6 arrangement's
  design reference is `apps/frontend/docs/figma/projects-chat-flow.md:113-126` (figma node
  `Web edit mode` 1339:41713 — "website artifact + Canvas Inspector") — prose only, no
  PNGs exist; the CONCRETE geometry truth is the dummy's own CSS: the `.chatPane |
  .artifactWorkspace` grid (`chat-shell.module.css:39-58`) and the existing
  `.chatBody`/`.inspectorDock`/`.composerDock` structure (§3.5). No new visual elements.

## 2. What exists today (scout-verified, 2026-08-19)

- **Route:** `apps/frontend/src/app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx`
  — server component; parses `{edit, handoff, selection, surface}` (:11-16); fetches ONLY
  `getProjectWorkspace(projectId)` (:31); renders `ProjectWorkspaceShell` with
  `initial={{edit, handoffId, selection, surface, threadId: chatId}}` (:34-45). **No
  artifact/document fetch of any kind.**
- **Tree:** page → `ProjectWorkspaceShell` (`features/projects/components/project-workspace-shell.tsx:14`)
  → `LoadedProjectWorkspace` (:52) → `useProjectWorkspaceController` (:59) +
  `useProjectChatController` (:63-66) → `ChatSurface`
  (`features/chat-shell/components/chat-surface.tsx:41`) with `paneState`.
- **ChatSurface internals:** `chatSurfaceUrlState(paneState)`
  (`model/chat-surface-params.ts:18-35`) → `useEditorShellController({editing,
  inspectorSelection, panelOpen, projectId, surface})` (:55-61) — **no `openArtifacts`
  seeded, so `artifactKind` is structurally always `null` there** and the guarded
  `editorVisible` (:72-76) is unreachable: `?surface=web` today renders conversation +
  composer + a rail showing the EMPTY gallery. The rail is `ArtifactStage` (:184-213) fed
  `artifacts={workspace.artifacts}` (:186), and `workspace.artifacts` is schema-hard empty
  (`features/projects/model/project-workspace.ts:317,330,346` — `z.tuple([])`).
- **The conversation column already has the R6 shape:** `.chatPane` (:86) → header (:87-99)
  → **`.chatBody` swap region (:100-130)** with three mutually exclusive branches — web
  inspector dock (:101-108, `styles.inspectorDock`), ad dock (:109-116), conversation
  (:117-129) — and the **composer as a SIBLING of `.chatBody`, always rendered**
  (:131-180, `.composerDock`/`.composerFrame`; CSS narrows the frame to 448px when the
  rail is open, `chat-shell.module.css:288-291`). The dock-swap machinery exists; it has
  simply never received real inspector props (today it gets two placeholder props,
  :103-106).
- **Send path (single choke point):** `ProjectComposer::submitCurrentDraft`
  (`features/projects/components/project-composer.tsx:77-95`) → injected `onSubmit` =
  `chat-surface.tsx:152-175`, which awaits `chat.submitMessage(...)` and checks
  `accepted.status === "accepted"` (:170). **The dismiss-on-send seam is
  `chat-surface.tsx:170-174`.**
- **URL write-back does not exist** (`chat-surface.tsx:36-38` documents the deferral):
  pane params are read once at mount; nothing writes `?surface=/?edit=/?selection=` back.
  The only `router.replace` is the handoff cleanup (`use-project-workspace-controller.ts:132-134`).
- **EditorSurface** (`features/chat-shell/components/editor-surface.tsx`) is NOT mountable
  in the rail as-is: it renders its own `<main>` (invalid nested in ChatSurface's), owns
  its own grid + its own `useEditorShellController`, and expects server-fetched
  `documentIds`. But every piece it composes is route-agnostic and prop-driven:
  `ArtifactStage`, `WebInspector` (pure props), `useWebArtifactSelection(documentId,
  reloadToken)`, `useInspectorWrites({document, documentId, onReload, selection})`,
  `useWebTheme(documentId)`, `useReplaceImage`, `buildWebLayerRows`,
  `buildThemeColorOptions` — all client-side through `designBffConfig()`.
- **The per-project artifact feed exists** (gallery lane, merged): the backend list read
  `GET /api/v1/projects/{id}/design-artifacts`, `loadGalleryFeed` +
  `toProjectArtifact` on the artifact page (`artifacts/[artifactId]/page.tsx:57-72,79-82`).
  The chats page just doesn't call it.

## 3. Architecture of the mount

**One shared editing-session hook; two thin layout owners.**

Extract the body of `EditorSurface`'s hooks region into
`features/design-editor/hooks/use-web-editing-session.ts`:

```ts
useWebEditingSession(input: {
  activeArtifactId: string | null;   // from the caller's OWN shell controller
  documentIds: Record<string, string> | undefined;
}): {
  activeDocumentId, webSelection, writes, onReplaceImage, layerRows,
  themeColors, canvasControls, reloadNonce, onWriteReload, inspectorSelection,
  /* + whatever lane C added to this region (rich-text session state,
     custom-component commits) — absorb its additions VERBATIM */
}
```

Key discipline: the hook **takes** `activeArtifactId` (and editing state where needed) as
input — it must NOT own a shell controller (the chats route already has one at
`chat-surface.tsx:55`; the artifact route keeps its own). `EditorSurface` becomes a thin
layout over the hook (artifact route: unchanged presentation); `ChatSurface` becomes the
second consumer (chat route: the dock + rail get real props). This is a refactor of the
exact region lane C is extending — hence the hard sequencing rule.

## 4. Slices

### Slice 1 — the chats route gets the real artifact feed
- `chats/[chatId]/page.tsx`: server-fetch the same feed the artifact page fetches
  (`loadGalleryFeed` — extract it from `artifacts/[artifactId]/page.tsx` into a shared
  server helper rather than duplicating; it returns cards + the `documentIds` map).
  Thread `{artifacts, documentIds}` through `ProjectWorkspaceShell` → `ChatSurface` →
  `ArtifactStage` (replacing `workspace.artifacts` at `chat-surface.tsx:186`).
- The rail's gallery now shows real cards on the chat screen; clicking a card opens a tab
  (`shell.openArtifact` wiring already exists, `chat-surface.tsx:194-200`).
- `workspace.artifacts` (`z.tuple([])`) stays untouched — the feed rides new props, not
  the workspace schema.
- Tests: the shared server helper (fixture-mocked); wire-shape. Browser: chat screen →
  rail → Gallery shows the real card; click → tab opens (canvas still empty — next slice).
- Commit: `feat(part4): chats-route artifact rail serves the real gallery feed`.

### Slice 2 — the shared editing-session hook (pure refactor)
- Extract `useWebEditingSession` exactly as §3; `EditorSurface` re-composes over it with
  ZERO behavior change (its file becomes layout + the hook call).
- Gate: the full suite green with NO test edits (behavior-identical refactor); the
  artifact route browser-smoked (select → edit → write → undo).
- Commit: `refactor(part4): the web editing session extracted for a second mount`.

### Slice 3 — the canvas renders in the chats-route rail
- `ChatSurface` consumes the hook (`activeArtifactId` from its existing shell controller,
  `documentIds` from slice 1) and passes the canvas wiring to `ArtifactStage`
  (`activeDocumentId`, `canvasControlsRef`, `canvasReloadToken`, `onCanvasSelect`,
  `selectedCanvasNodeId`, undo/redo disables — the props the artifact route already
  passes and the chats route currently omits).
- Browser: open the chat screen → click the gallery card → the real page renders in the
  rail; canvas selection outlines work; undo/redo menu states real.
- Commit: `feat(part4): the web canvas live in the chats-route artifact rail`.

### Slice 4 — R6: the dock choreography
- The `.chatBody` web-inspector branch (`chat-surface.tsx:101-108`) receives the REAL
  `WebInspector` props from the hook (`addressing`, `hydrated`, `layers`,
  `onReplaceImage`, `onSelectLayer`, `onSelectionChange`, `selection`, `themeColors`,
  error/note) — the same prop set `EditorSurface` passes, keyed per selected node.
  `editorVisible` becomes reachable (its guard already requires editing + web kind +
  an open artifact — Edit-only entry holds by construction).
- **Dismiss-on-send:** at `chat-surface.tsx:170-174`, after `accepted.status ===
  "accepted"`, call the shell's editing-off action (dock closes, conversation returns).
  Nothing in `ProjectComposer` changes.
- The composer stays pinned (it already is — assert it in the browser pass, don't touch
  it).
- Tests: params/controller-level (dismiss on accepted submit; NOT dismissed on refused/
  empty submit — `submitMessage` returns `not_submitted` on empty/no-thread); Edit-only
  entry (no dock without editing+artifact).
- Browser (the acceptance choreography, all on the chat screen): real conversation →
  open artifact from rail → Edit → transcript replaced by inspector, composer still
  at bottom → edit text on canvas (write persists) → type a message + send → dock
  dismisses, conversation returns, the agent message posted → Edit → dock returns.
- Commit: `feat(part4): R6 live — inspector over the conversation column, send dismisses (chat-flow integration)`.

### Slice 5 — URL state write-back (closing the known deferral)
- Pane toggles write back: opening/closing the rail, switching surface, Edit on/off,
  selection changes → `router.replace` with the ratified params (`?surface=`, `?edit=1`,
  `?selection=`), preserving the R2 vocabulary; parsing already exists
  (`chat-surface-params.ts`). Deep-link in = already works (read-at-mount); this makes
  deep-link OUT true (shareable editing state).
- Handle the ratified-but-unparsed `?surface=chat` value explicitly (today it falls
  through to undefined — same rendered result, but parse it deliberately and test it).
- Tests: params round-trip (state → URL → state identity).
- Commit: `feat(part4): chats-route pane state round-trips through the ratified URL params`.

### Slice 6 — close-out
- Record the composer-stays clarification in the Phase-C plan's R6 bullet (dated).
- Contract notes into `apps/frontend/docs/api-contracts/projects.md` (the chats-route
  feed props; the write-back).
- Full gates (`npm test`/lint/design-system:build/build + `make check`), `_memory/`
  close-out, founder walkthrough script (the slice-4 choreography above).

## 5. Constraints & traps

- **Sequencing: after lane C merges. Non-negotiable** (§7 collision table in the scout
  report: lane C +181 in `editor-surface.tsx`'s hooks region, +508 in
  `web-inspector.tsx`, +25 in `artifact-stage.tsx`). Slice 2 must absorb lane C's
  session additions (rich-text, custom-component) into the hook verbatim.
- The artifact route must stay pixel- and behavior-identical through every slice (its
  smoke is part of every slice's gate).
- No new UI anywhere: the dock, tabs, header, composer, gallery are all the dummy's own;
  R6 is a re-plumbing of existing regions. Anything that seems to need a new visible
  element → founder gate first.
- `web-inspector.tsx` should ideally take ZERO new lines (a second call site passes
  existing props).
- Presentation never imports `data/`/engine (seam lint); the hook lives in
  `features/design-editor/hooks/`; server fetches live in the page/server helpers.
- Repo traps: `tsx --test` runner (NOT vitest); no sync `setState` in effects; no
  render-time ref writes; don't shadow `document`; port-check before every server launch
  (three incidents on the trunk); `LUMEN_CORE_HELPER` mandatory for the design API; any
  `lumen-web` change requires a helper rebuild + API restart (not expected here — this
  plan is frontend-only).
- Environment: trunk stack 3030/8030/8010, test login in
  `_memory/2026-08-17-w01-shell-lift-file-set.md`; a real conversation thread is needed
  for slice 4's send test (use the seeded project's existing thread).

## 6. Out of scope (recorded)

1. Ad-surface editing (`?surface=ad` — the ad-editor plan owns it; the ad dock branch
   stays placeholder).
2. Agent-streaming/turn integration with the editor (agent edits arriving live on the
   canvas) — separate plan.
3. The `?handoff=` flow (existing behavior untouched).
4. Maximize/split "focused workspace" transitions beyond what the dummy CSS already does.
5. Publishing/share chrome (own contracts).

**Done means:** a marketer chats with the agent, opens the produced website from the
rail's gallery, presses Edit, tunes it in the inspector while the conversation waits
underneath, sends a follow-up instruction — the dock yields to the conversation exactly
as ruled — and deep-links any of those states to a teammate.
