# Lane 1 / Phase C — Chat Chrome Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Sequencing:** starts ONLY after the Phase R exit gate (`docs/superpowers/plans/2026-08-17-phase-r-chat-route-migration.md`). Lane map: Lane 1 = Phase R → this plan; Lane 2 = W-phases (website editor); Lane 3 = co-founder accounts parity.

**Goal:** The chats route (`/projects/{id}/chats/{chatId}`) renders the co-founder's chat-shell design — header, session menu, docked composer, artifact rail — with OUR production chat (transcript, gates, streaming, queue/Stop, refusal states) slotted into its geometry, pixel-faithful to the dummy build.

**Architecture:** The dummy's chat shell is *pure geometry* (its conversation area is an empty `<div>`; its composer is wired to no-ops — verified in the tri-area diff). Adoption is therefore: restore the chat-chrome CSS block our W0.2 bisection deliberately excluded, lift the header/session-menu chrome verbatim, re-author the shell-view composition without its embedded `ApplicationShell` (ruling R7 — our layout owns the shell), and mount our existing transcript/composer/alert components into the design's slots. Our composer is KEPT (theirs is an ancestor fork missing four production fixes); our chat wiring is untouched end to end.

**Tech Stack:** Next.js App Router (apps/frontend, npm, node:test via `tsx --test`), CSS Modules, the existing `useProjectChatController`/`useProjectWorkspaceLoader` production chat plane.

**Spec:** Founder rulings R4–R7 (2026-08-17) + the chat-area/tri-area diff reports, recorded in `_memory/2026-08-17-frontend-tri-diff-synthesis.md`. Source tree: `/tmp/clue-frontend-tip` (clue-hq/clue-frontend@codex/chat-shell, c7f2bc5) — re-clone with `gh repo clone clue-hq/clue-frontend /tmp/clue-frontend-tip -- --depth 50 -b codex/chat-shell` if absent. Visual reference: dummy build running at `localhost:3080`.

## Global Constraints

- **Visual parity is absolute** (parity constitution, `apps/frontend` memory + `_memory/`): the dummy build is baseline and ceiling. No invented UI. Raw ids/field keys never render.
- **R4:** no in-shell thread switcher or new-thread affordance — the sidebar owns thread switching (deliberate design decision). The in-pane `<select>` is removed, not hidden.
- **R5:** the session menu's **Delete** item renders but is **inert** (no handler beyond its aria-live acknowledgement pattern; no backend call). Archive and Rename are wired to the real controller.
- **R6 (accepted for v1):** while `editing`, the inspector replaces the conversation column — founder personally owns revisiting this during editor integration. Implement as designed; do not soften it. **RATIFIED 2026-08-18 — the owned revisit happened; the dummy's arrangement is confirmed as the co-founders' planned design ("we have to follow what the dummy does"). Two behavioral clarifications ratified with it: (1) the ONLY way the inspector dock takes over the conversation column is the Edit button while a specific artifact is open — no other trigger, ever; (2) on the chat screen, the moment the user sends a message to the agent, the dock dismisses and the conversation column returns; getting the dock back is Edit again. Clarification (2) is chat-flow-integration wiring (it hangs off the composer's send event on the chats-route mount) — not W4 scope; it binds whoever wires editing into the chats route. The artifact route's editing dock (website-editor plan W2.3) is this same arrangement transposed to a chat-less route and was signed off with the W2 exit gate the same day.** **Composer clarification (founder, 2026-08-19): while the dock is open, the composer remains visible and usable below it — the dock replaces the conversation TRANSCRIPT only, never the composer (structurally guaranteed: the composer is a sibling of `.chatBody`, not a child). R6 went LIVE 2026-08-19 via the chat-flow editor integration (slices 4–5, commits `3ba169be` + `95922696`): Edit docks the real inspector, an ACCEPTED send dismisses it (refused/empty submits do not), and the pane state round-trips through the ratified `?surface=/?edit=/?selection=` params.**
- **R7:** our layout-level `ProjectApplicationShell` owns the app shell. Lifted view code must have its `<ApplicationShell>` wrapper stripped. `useApplicationSidebar()` throws outside our shell — the lifted header must not call it; the existing sidebar trigger behavior stays where it lives today.
- **Keep-ours (binding verdicts from the diff):** our composer (`project-composer*` — theirs lacks submit accept/reject+lock, `clearSubmittedDraft` undo-scrub, controlled prompt, external entity sync); our model-picker (a11y-correct `menuitemradio`); our `ProjectIcon` (their `chat-icon.tsx` and `/icons/chat/*` assets are NOT lifted — they belong to their forked composer only); our chat controller and all repositories/stream/gates wiring; our `use-editor-shell-controller` (no default-tab fabrication).
- **Do not adopt:** their `use-chat-shell-controller.ts` (hardcoded `gpt-5.5`, fabricated default tabs, local-state chat title), their `createInitialOpenArtifacts`, their `window.history.pushState` thread simulation, their `/chat/*` shim routes, the dead prototype tree.
- **Known-empty state:** `workspace.artifacts` is `z.tuple([])` until W1.3's read seam lands — the artifact tab strip on the chats route legitimately shows only the Gallery tab. Do not fabricate tabs.
- Frontend gate: `cd apps/frontend && npm test && npm run lint && npm run build`. Commit locally per task; **never push**; no AI attribution.

---

### Task C-1: Restore the chat-chrome stylesheet block

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css`
- Source: `/tmp/clue-frontend-tip/src/features/chat-shell/components/chat-shell.module.css` (2,941 lines)

**Interfaces:**
- Produces: the chat-chrome classes later tasks' components reference: `.shell`, `.shellPanelOpen` (standalone grid rules), `.shellArtifactMaximized`, `.chatPane`, `.chatHeader`, `.chatTitleCluster`, `.chatTitleMenuAnchor`, `.chatTitleButton` (+`:hover`, `Active`, `:focus-visible`, `span`), `.chatTitleLabel`, `.chatTitleRenameInput` (+`:focus`), `.chatSessionMenuButton` (+states), `.chatSessionMenu`, `.chatSessionMenuIcon`, `.conversationStage`, `.composerDock`, `.composerFrame`, and the `.shellPanelOpen`/`.shellArtifactMaximized` variants of `.composerDock`/`.composerFrame`/`.chatPane`.

- [ ] **Step 1:** Extract from the source stylesheet every rule whose selector involves the classes above (they live in the source's lines ~1–300 chat region, the shared button-reset selector list, and the responsive tail) and merge them into our bisected module in source order. Re-point the shared button-reset: our narrowed reset gains `.chatTitleButton` and `.chatSessionMenuButton`. Restore the chat selectors trimmed from the responsive/reduced-motion tail (`.shellPanelOpen` grid rules at 1180px/760px, `.shellPanelOpen .chatPane`, `.shell`/`.composerFrame` in the final reduced-motion block).
- [ ] **Step 2:** Do NOT lift the dead rules (dead in **both** trees, verified): `.artifactTab` (single), `.editorToolButton`, `.editorToolButtonActive`, `.editorToolGroup`, `.imageEditorToolbar`, `.smallIconButton`, `.chatTitleButton*`-only-if-unreferenced — check each lifted class against actual `styles.*` references after C-2/C-4 land (final audit step in C-5).
- [ ] **Step 3:** Preserve the W0.2 alias-carrier invariant: the `--chat-shell-*` variables must additionally ride `.shell` (the new chat root) — extend the carrier rule (`.artifactWorkspace, .chatBody, .inspectorDock` → add `.shell`). Verify `.shellPanelOpen .artifactWorkspace { opacity: 1 }` still cascades identically (the editor-surface mount depends on it — `editor-surface.tsx:45`).
- [ ] **Step 4:** Brace-balance check (`python3 -c "s=open('...').read(); assert s.count('{')==s.count('}')"`), `npm run design-system:build && npm run build` green.
- [ ] **Step 5:** Commit: `feat(chat-chrome): restore the chat-chrome stylesheet block per Phase C (C-1)`.

### Task C-2: Lift the chat header + session menu, rewired to real thread actions

**Files:**
- Create (from source, adapted): `apps/frontend/src/features/chat-shell/components/chat-shell-header.tsx`, `chat-session-action-menu.tsx`
- Create (from source, adapted): `apps/frontend/src/features/chat-shell/hooks/use-chat-session-menu-controller.ts`
- Create (verbatim): `apps/frontend/src/features/chat-shell/model/chat-session-actions.ts` + `.test.ts`
- Test: `apps/frontend/src/features/chat-shell/hooks/use-chat-session-menu-controller.test.ts` (new — the source ships none)

**Interfaces:**
- Consumes: `chat.renameThread(threadId, title)` and `chat.archiveThread(threadId)` from `useProjectChatController` (verify exact signatures in `use-project-chat-controller.ts` before wiring — they exist per the diff report; adapt call shape to what is found, never invent).
- Produces: `<ChatShellHeader chatId title onRename onToggleArtifactPanel panelOpen projectId />` with a working rename-in-place input and a session menu whose items behave per rulings.

- [ ] **Step 1:** Copy the three source files. The source controller's three `window.dispatchEvent` CustomEvents (`clue:chat-session-rename`, `clue:chat-session-action-request`, `clue:chat-session-id-copy`) are a stub bus with **no listener in either tree** — replace them with injected callbacks: the controller takes `{ onArchive: () => Promise<void> | void, onRename: (title: string) => Promise<void> | void }`; copy-session-id keeps its clipboard write + aria-live message.
- [ ] **Step 2 (R5):** The menu's **Delete** item stays rendered with its destructive styling and receives **no callback** — clicking it does nothing (not even the aria-live "requested" message, which would be a false success claim). Add a one-line code comment citing R5.
- [ ] **Step 3:** Write the controller tests (node:test, same pure-function pattern as `use-editor-shell-controller.test.ts`): rename draft/commit/cancel semantics, Escape/outside-pointer dismissal state transitions, archive invokes the injected callback, delete invokes nothing.
- [ ] **Step 4:** `npx tsx --test src/features/chat-shell` → green; `npm run lint && npm run build` green.
- [ ] **Step 5:** Commit: `feat(chat-chrome): chat header + session menu lifted; rename/archive wired, delete inert (R5)`.

### Task C-3: The chat surface — design geometry around our production chat

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` — the re-authored `chat-shell-view.tsx` composition (source: `/tmp/clue-frontend-tip/src/features/chat-shell/components/chat-shell-view.tsx`)
- Modify: `apps/frontend/src/features/projects/components/project-workspace-view.tsx` and/or `project-workspace-shell.tsx` — the chats route's shell renders `ChatSurface` as its view layer
- Modify: `apps/frontend/src/features/projects/components/conversation-pane.tsx` — extraction refactor (see Step 2)

**Interfaces:**
- Consumes: `useProjectChatController` (transcript, alerts, queue state, submit, gates), `useEditorShellController` (artifact rail state), `ChatShellHeader` (C-2), `ArtifactStage` (existing), `ProjectComposer` (existing), the C-1 CSS classes.
- Produces: the ratified layout — `main.shell(.shellPanelOpen)(.shellArtifactMaximized)` → `section.chatPane[ChatShellHeader + div.chatBody[conversation OR inspector] + div.composerDock>div.composerFrame[ProjectComposer]]` + `ArtifactStage` — with `?surface=`-driven pane state.

- [ ] **Step 1:** Author `chat-surface.tsx` from the source view's JSX structure with these binding substitutions, each traceable to a diff verdict:
  - **No `<ApplicationShell>` wrapper** (R7) — the component's root is `main.shell`.
  - `.conversationStage` slot ← our conversation content: the four `role="alert"` refusal lines, `ChatTranscript`, the queue/Stop banner, `ChatTurnInspector` affordance — everything `conversation-pane.tsx` renders today **except** the thread `<select>` + new-thread button (R4: removed entirely) and except the composer (which moves to the dock slot).
  - `.composerFrame` slot ← our `ProjectComposer` with its full existing prop wiring (capability gating, `sendDisabled`, `clearSubmittedDraft` handle, contextRefs mapping — move the wiring intact from conversation-pane).
  - Header ← `ChatShellHeader` with `onRename={(t) => chat.renameThread(activeThreadId, t)}`, `panelOpen`/`onToggleArtifactPanel` from the editor-shell controller's surface state.
  - Inspector dock (R6, as designed): when `editing && artifactKind === "web"` render `WebInspector` in `.inspectorDock` replacing the conversation; `"ad"` branch renders `ImageInspector` (present but unreachable until an ad artifact exists — same posture as W0).
  - `data-*` attributes as in source (`data-artifact-id/kind/editing/project-id`) minus the fixture-era `data-phase`.
- [ ] **Step 2:** Extract, don't duplicate: the conversation content moves out of `conversation-pane.tsx` into a `ConversationContent` component both old and new layouts can render during the transition; the old `ConversationPane` becomes a thin wrapper (or is deleted if nothing else consumes it after this task — check imports and delete if orphaned; dead wrappers violate DRY).
- [ ] **Step 3:** Wire `?surface=` (from Phase R's reserved parsing) into the surface state: `gallery` → gallery surface active in the artifact rail; `web|ad` → activate/maximize the artifact surface (`?edit=1` → `editing`; `?selection=` → `parseChatShellInspectorSelection`). URL is read-on-mount initial state only in this phase (no URL write-back on toggle — note it as a known deferral, matching the dummy's own behavior).
- [ ] **Step 4:** Tests: extend `use-editor-shell-controller.test.ts` if new surface actions are added; node:test any new pure mapping (`searchParams → initial state`) as a `model/` function with fixtures.
- [ ] **Step 5:** Browser-verify against `localhost:3080`'s chat screen side-by-side: header geometry, composer dock, artifact rail; then verify **all production behaviors survived**: send message, streaming render, gate card interaction, queue banner + Stop, refusal alerts (`THREAD_NOT_FOUND` in-pane per R10 default), add-to-chat handoff.
- [ ] **Step 6:** Commit: `feat(chat-chrome): chats route renders the designed chat shell around production chat (R4, R6, R7)`.

### Task C-4: Home composer variant

**Files:**
- Modify: `apps/frontend/src/features/projects/components/project-composer.tsx` — add `variant?: "default" | "home"` (presentation-only; from the source's `chat-composer.tsx`)
- Modify: `apps/frontend/src/features/projects/components/project-flow.module.css` — add the `.composerHome` class (the single class ours lacks, per the diff; copy from the source's `chat-composer.module.css`)
- Modify: `apps/frontend/src/features/projects/components/project-home-view.tsx` — pass `variant="home"`

- [ ] **Step 1:** Copy the `.composerHome` rule block; add the `variant` prop mapping to the class exactly as the source composer does; pass it from Home.
- [ ] **Step 2:** `npm test && npm run lint && npm run build` green; browser-verify Home against 3080's Home (the composer card geometry).
- [ ] **Step 3:** Commit: `feat(chat-chrome): home composer variant per design (C-4)`.

### Task C-5: Parity audit + close-out

- [ ] **Step 1:** Class-coverage audit (both directions, the W0.2 method): every `styles.*` reference across all chat-shell + chat-surface components resolves; every C-1-restored class is referenced (or documented as awaited); no dead lifts.
- [ ] **Step 2:** Side-by-side browser pass vs 3080 for: chat view (empty + with transcript), rename-in-place, session menu open (Delete visibly present, inert), maximized artifact state, gallery surface, reduced-motion spot check. Screenshot pairs saved to `/tmp/phase-c-parity/`.
- [ ] **Step 3:** Full gates (`npm test && npm run lint && npm run build`), `_memory/` close-out note (include: what R6 defers to the founder's editor-integration pass; the known-empty artifact tabs pending W1.3; any discovered upstream drift — re-diff lifted files against the branch tip first, per the standing re-sync rule).
- [ ] **Step 4:** Commit: `feat(chat-chrome): phase C complete — designed chat shell live on the chats route`.

**Phase C exit gate:** a user on `/projects/{id}/chats/{chatId}` sees the co-founder's chat design, pixel-faithful side-by-side with 3080, while every production chat behavior (streaming, gates, queue/Stop, refusals, handoff, archive/rename) works unchanged; Delete visibly present and inert; no thread switcher in-shell; npm gates green.

---

## Convergence notes

- **With the W-lane:** `?surface=web|ad` + `?edit=` + `?selection=` on the chats route is the split-view mount the editor lane will hydrate (W2+ read path, real canvas). Phase C delivers the geometry and URL contract; the W-lane fills the canvas and inspector with real data. Any route/param need discovered in the W-lane is a contract change — it comes back here, never resolved locally (the stop-rule).
- **With Lane 3:** no shared files with the accounts tree; merges are order-free.
- **Dead-code note:** their orphaned prototype tree and our dead gallery CSS in `project-flow.module.css` are explicitly out of scope — separate cleanup PR after the design-integration trigger condition (see repo CLAUDE.md backlog).
