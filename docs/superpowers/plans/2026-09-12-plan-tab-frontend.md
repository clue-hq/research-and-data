# Plan Tab Frontend Implementation Plan (Lane 2, plan 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** frontend implementation and acceptance COMPLETE, 2026-09-14, including the Task 8
founder amendment replacing the permanent Plan tab with named file tabs. See
[`2026-09-14-lane2-flow-acceptance.md`](2026-09-14-lane2-flow-acceptance.md). Originally
re-activated as Lane 2's first plan on 2026-09-13 after R12 deferred it; the historical tasks
below describe that sequence, with Task 8's amendment governing the final tab behavior.

**Re-validated against `2026-09-13-agent-workspace-reorganization-design.md` (W6):** the agent will stop calling `write_project_document@1` once Lane 1's plan 3 lands and will write `project/plan.md` with its file tool instead; the plan card is then rendered from the turn's document rows. This plan therefore keys the auto-open on the **plan part** in the transcript (Task 7), which exists in both worlds, not on a tool call. The document list/detail/PUT routes are unchanged by Lane 1. Persona documents live at `audience/persona-<key>.md` (ruling P3-a), so Task 8's gallery cards use the existing `icp_key` on the wire and need no path assumptions.

**Goal:** The user reads and edits the project's `plan.md` in a Plan tab beside Gallery and Target accounts; the "proposed a plan" card in the chat opens the tab; the tab opens itself when the agent writes the plan; project-scoped ICP and persona documents appear in the gallery as document cards and open on the same surface.

**Architecture:** Surface `"plan"` joins the chat shell; `ProjectDocumentSurface` is built from the Knowledge editor's pieces lifted into `components/markdown/` (react-markdown + remark-gfm for preview, MDXEditor for visual editing — revised ruling R10, 2026-09-13); a pure `planWriteToOpen` signal transports the auto-open; the gallery gains document cards.

**Tech Stack:** Next.js App Router + TypeScript, Zod, CSS modules with `@clue/design-system` tokens, `react-markdown` + `remark-gfm`, `@mdxeditor/editor`; `node --test` via `tsx`.

**Spec:** `docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.3 (rulings R6, R7, R10, R11, R12). Depends on `docs/superpowers/plans/2026-09-12-project-plan-document.md` Tasks 1–3 and 9 (the backend and the grant).

## Global Constraints

- Presentation truth is the dummy's Plan tab (ruling R6); every style uses `--clue-ds-*` tokens; the token test stays green.
- Rendering and editing use external libraries only (revised ruling R10): `react-markdown` + `remark-gfm` for preview, MDXEditor for visual editing. No in-house Markdown parser, serializer or formatting commands.
- Task 5 introduces the MDXEditor foundation and content-preservation checks. The complete composed toolbar (revised R11) remains plan 2; retain Preview/Edit and Save/Discard in the document header.
- Use the active Semarang frontend origin and its own database/configuration for verification; do not use another lane's :3020 examples or stop sibling services.
- Frontend architecture, test runner and gate as in the parent plan.

The task numbering keeps the parent plan's numbers (4–8) so cross-references hold.

---

### Task 4: Frontend model, repository, BFF

**Files:**
- Create: `apps/frontend/src/features/projects/model/project-documents.ts` (+ `.test.ts`), `apps/frontend/src/features/projects/data/project-documents.repository.ts`, `project-document-actions.ts`, `project-documents-error.ts`, `apps/frontend/src/app/api/projects/[projectId]/documents/route.ts`, `apps/frontend/src/app/api/projects/[projectId]/documents/[documentId]/route.ts` and their shared `project-documents-handler.ts` (+ focused repository/action/BFF tests).
- Delete: `apps/frontend/src/features/projects/components/project-plan.tsx`; remove `ProjectPlanSchema` and `export type ProjectPlan` from `model/project-workspace.ts`

**Interfaces:**

```ts
// model/project-documents.ts
export const ProjectDocumentKindSchema = z.enum(["project-plan", "icp-definition", "audience-persona"]);
export const ProjectDocumentSummarySchema = z.object({
  id: z.string().min(1), path: z.string().min(1), kind: ProjectDocumentKindSchema,
  title: z.string().min(1), version: z.number().int().positive(), status: z.string().min(1),
  updated_at: z.string().min(1), icp_key: z.string().nullable(),
});
export const ProjectDocumentDetailSchema = ProjectDocumentSummarySchema.extend({
  markdown: z.string(), front_matter: z.record(z.string(), z.unknown()),
});
export const ProjectDocumentsResponseSchema = z.object({ data: z.object({ documents: z.array(ProjectDocumentSummarySchema) }) });
export const ProjectDocumentDetailResponseSchema = z.object({ data: ProjectDocumentDetailSchema });
export interface ProjectDocument { id; path; kind; title; version; status; updatedAt; icpKey }   // camelCase view
export interface ProjectDocumentDetail extends ProjectDocument { markdown: string; frontMatter: Record<string, unknown> }
export function toProjectDocument(wire): ProjectDocument
export function planDocumentOf(documents: readonly ProjectDocument[]): ProjectDocument | null   // path === "project/plan.md"
export function documentEditedLabel(updatedAt: string, now: Date): string   // "Edited just now" | "Edited 5 min ago" | "Edited today at 14:02" | "Edited 12 Sep" — pure, tested
```

```ts
// data/project-documents.repository.ts
export async function listProjectDocuments(projectId, read = fetchRead): Promise<ProjectDocument[]>
export async function getProjectDocument(projectId, documentId, read = fetchRead): Promise<ProjectDocumentDetail>
// data/project-document-actions.ts — browser-safe; do not import the server read repository in an editor
export async function saveProjectDocument(projectId, document: ProjectDocument, body: string, clueFetch = fetch): Promise<ProjectDocumentDetail>
//   PUT /api/projects/{projectId}/documents/{id} with { body, expectedRevision: document.version }
//   409 → "A newer version of this document exists. Your changes are still here; copy them before loading the latest version."
//   401/403 → "You do not have permission to edit this document."
```

BFF routes copy `app/api/projects/[projectId]/discovery/route.ts`: `GET` list; `GET` detail; `PUT` forwards `{ body, expected_revision: expectedRevision }` through the authenticated backend client used by the accounts bulk-action route (find the mutation helper that route uses; it already enforces origin and workspace stamping), returns the backend status and body verbatim on 409/401/403.

- [x] **Step 1: Failing model tests** — schema parse of a list payload; `planDocumentOf`; `documentEditedLabel` for the four cases.
- [x] **Step 2–4: implement; run `npm test`, `npm run lint`.**
  - **2026-09-13:** implemented all three BFF methods, authenticated server reads, browser saves,
    immutable returned IDs/revisions, unchanged-body transport, permissions/conflict errors and
    orphan removal. Front matter is retained for reads and never writable through the BFF.
    Save actions are separated from server reads because a browser bundle of the original
    combined module pulled in server authentication/Node built-ins. This follows the existing
    Knowledge repository/actions split; the backend contract is unchanged. Full test suite,
    design-token build, lint and production build passed; final verification is in
    `_memory/2026-09-13-lane2-project-document-connection.md`.
- [x] **Step 5: Commit** — local checkpoint: `feat(frontend): connect project documents with versioned saves`.

---

### Task 5: Shared Markdown preview and MDXEditor foundation

**Decision update, 2026-09-13:** the founder selected MDXEditor. Introduce the shared visual
editor directly; do not first extract CodeMirror only to replace it in plan 2.

**Files:**
- Create: `apps/frontend/src/components/markdown/markdown-article.tsx`, `markdown-editor.tsx`,
  `markdown-editor-client.tsx`, `markdown.module.css` and focused integration test fixtures.
- Modify: `apps/frontend/package.json` / lockfile for a verified published `@mdxeditor/editor`
  release; Knowledge panel/header and `use-knowledge-editor.ts` for the shared editor lifecycle.
- Remove after migration: `features/brand-context/components/markdown-source-editor.tsx`,
  `hooks/use-markdown-source-editor.ts` and unused editor CSS. Move preview styles to the shared
  module. Keep any CodeMirror packages used elsewhere or by library source/code plugins.

**Shared seam:**

```tsx
export function MarkdownArticle({ markdown, className }: { markdown: string; className?: string })
// Preview uses react-markdown + remark-gfm.

export function MarkdownEditor({ documentKey, value, resetKey, onChange, readOnly }: {
  documentKey: string; value: string; resetKey: number;
  onChange: (value: string) => void; readOnly: boolean;
})
// Client boundary lazy-loads the initialized MDXEditor and plugins with ssr:false.
// value initializes the session; changes from typing are emitted, not fed back as replacements.
// resetKey changes for explicit resets (e.g. Discard), not every keystroke or refreshed UUID.
```

Scope the session by workspace/project and stable document path. Feature hooks retain raw saved
body, base revision and drafts; the shared adapter controls only the editor lifecycle. MDXEditor's
initial normalization must not create a draft. Preserve the original body for untouched saves;
verify undo back to the initial state. Use public library lifecycle APIs for external replacement,
and preserve the session through Preview/Edit. A refreshed version must not erase dirty changes.

Enable the native plugins required to import existing headings, inline marks, lists, tables, links
and code blocks before migrating Knowledge. Retain source recovery for unimportable content and
never send an empty replacement after a parser failure. See the revised toolbar brief for the
content-preservation contract. Plan 2 supplies the complete toolbar, not a second editor.

Preview and editor prose use Clue typography tokens; code and source mode use code tokens.
Map library public CSS variables/classes and icon overrides to Clue, including dialogs/popovers.
Vendor structural CSS is retained. Constrain the whole panel width; tables/code cannot widen
the surrounding chat, and long URLs/inline code/source text wrap. No source line numbers.

- [x] **Step 1: Compatibility prototype.** Verify a published MDXEditor release in this Next/React
  checkout, including client-only plugin imports and coexistence with existing Lexical dependencies.
  Do not force unrelated package versions. Exercise a disposable representative Markdown document.
  - **2026-09-13 prototype:** `prototypes/mdx-editor/` runs on port 3047 with real controls,
    Clue tokens, browser-only demo saves and source recovery. Next/React checks pass with
    MDXEditor 4.2.5's Lexical 0.48 tree. The app's existing Lexical 0.49 packages produced
    duplicate-instance errors in the first browser experiment. This initial gate was resolved in the main-app migration below; see the prototype README.
- [x] **Step 2: Shared integration.** Extract `MarkdownArticle`, introduce the MDXEditor boundary,
  then migrate Knowledge. Preserve canEdit/read-only rules, Save/Discard, draft base revision,
  conflicts and the return of a new document ID on save. Keep repository calls outside the editor.
- [x] **Step 3: Verify.** Focused draft/adapter tests and browser interactions for no-op opening,
  initial normalization, edits/undo, source recovery, Preview/Edit, Discard, switching documents
  and long-content wrapping. Run relevant Brand Context tests plus frontend lint/build/token tests.
- [x] **Step 4: Commit** — `refactor(frontend): shared Markdown preview and MDXEditor foundation`.

---

**2026-09-14 implementation / acceptance:** shared components now live in
`src/components/markdown/`; Knowledge uses the approved native MDXEditor toolbar and
shared library preview. Direct Lexical packages are aligned to 0.48.0 (no overrides),
with a constructor-identity regression and the existing design text tests passing.
DM Mono is self-hosted, matching the code token. Session identity is workspace + path;
Save adopts the returned immutable ID/revision, and refresh cannot replace a dirty base.
Native source recovery retains the draft and requires valid Rich text before Save.

Browser acceptance on Semarang 3040: clean opening of the existing Knowledge document;
Preview/Edit undo to clean; a disposable document saved as v2 and v3 and survived reload;
a second tab's stale save returned a conflict and retained its draft; source errors,
document switching, Discard and 360 px rich/source/preview containment passed. The
fixture paths were removed afterward; original Knowledge documents were not edited.
The 2,254-test frontend suite, design-system build, lint and production build passed.
Task 6 (Plan UI) remains separate. The local database still lacks Lane 1's project_id
column on brand_knowledge_document; backend/schema rollout is required before the later
project-document browser walk, and was not changed for this Knowledge migration.

---

### Task 6: The Plan surface — shell state, tab, pane, editor hook

**Visual-review checkpoint — 2026-09-14:** the founder's agreed step 4 starts with a
reviewable preview. `prototypes/mdx-editor/app/plan` serves it at
`http://localhost:3047/plan`, reusing the approved prototype editor/session. It shows
the third tab, document header, centered article, prescribed empty state, 360 px
layout, local sample Save/Discard, plan-card opening and simulated plan arrival.
This is sample-data UI only. The production Task 6 and Task 7 checkboxes below stay
open until visual approval and real shell/repository/transcript integration. The
local backend/schema rollout identified after Task 5 is still required for the live
project-document acceptance walk.

**Files:**
- Modify: `features/chat-shell/model/chat-shell.ts` (`ChatShellSurface` adds `"plan"`), `features/chat-shell/hooks/use-editor-shell-controller.ts` (`EditorShellSurface` adds `"plan"`; action `{ type: "open-plan" }` → `{ ...state, editing: false, panelOpen: true, surface: "plan" }`; `openPlan` on the controller), `features/chat-shell/model/chat-surface-params.ts` (`parseChatSurface("plan")`; `chatSurfacePaneParams` returns `{ ...NO_PANE_PARAMS, surface: "plan" }`; both `surface` unions add `"plan"`) + `chat-surface-params.test.ts`
- Create: `features/projects/hooks/use-project-documents.ts`, `features/projects/hooks/use-project-document-editor.ts`, `features/projects/components/project-document-surface.tsx`, `project-document-surface.module.css`
- Modify: `features/chat-shell/components/artifact-tabs.tsx` (third tab), `artifact-stage.tsx` (the pane), `chat-surface.tsx` (props)

**Interfaces:**

```ts
// hooks/use-project-documents.ts
export function useProjectDocuments(projectId: string, { active, refreshToken }: { active: boolean; refreshToken?: number }): { documents: ProjectDocument[]; plan: ProjectDocument | null; loading: boolean; reload: () => void }
//   first load when `active` becomes true; refetch on `refreshToken` change (the plan-write signal bumps it)

// hooks/use-project-document-editor.ts — the Knowledge editor's state machine with an injected save
export function useProjectDocumentEditor(
  document: ProjectDocumentDetail | undefined,
  save: (document: ProjectDocument, body: string) => Promise<ProjectDocumentDetail>,
): { body; canEdit; dirty; discard; editorOpened; mode: "preview" | "edit"; error; save; setBody; saving; busy; saved; setMode; resetKey }
// resetKey advances on Discard or an accepted external replacement of a clean session.
// Typing and a new version UUID alone do not reset the editor. Knowledge uses the same rule.

// components/project-document-surface.tsx
export function ProjectDocumentSurface({ active, documentId, projectId, refreshToken }: { active: boolean; documentId: string | null; projectId: string; refreshToken?: number })
//   documentId null → the plan (planDocumentOf); renders the empty state "No plan yet. Once the strategy, the profile and the products are settled, the plan is written here." when absent.
```

Layout (from the screenshot, tokens only): `.surface` grid `auto minmax(0,1fr)`; `.header` height 58px, `border-bottom: var(--clue-ds-product-border-grid-width) solid var(--clue-ds-color-border-subtle)`, padding `16px 24px 12px`, flex, space-between; `.name` inline-flex gap 4px with `<ProjectIcon name="file-text" size={12} />` and the title in `--clue-ds-typography-text-sm-medium-*`; `.controls` reuse the segmented control + primary/secondary button rules from `brand-context.module.css` (copy the blocks; they are token-based); `.scroll` `overflow-y: auto`; the article is `<MarkdownArticle>` centred with `max-width: 720px; margin: 0 auto; padding: 48px 48px 96px`; background `var(--clue-ds-color-bg-neutral)`; surface entry animation `surface-in var(--clue-ds-product-motion-duration-view) var(--clue-ds-product-motion-easing-entry)` like `.projectPlan` had.

`artifact-tabs.tsx`: after the Target accounts button, when `onOpenPlan` is provided:

```tsx
{onOpenPlan ? (
  <button aria-selected={surface === "plan"} className={`${styles.galleryTab} ${surface === "plan" ? styles.galleryTabActive : ""}`} onClick={onOpenPlan} role="tab" tabIndex={surface === "plan" ? 0 : -1} type="button">
    <ProjectIcon name="file-text" size={12} />
    <span>Plan</span>
  </button>
) : null}
```

`artifact-stage.tsx`: `onOpenPlan?: () => void; planRefreshToken?: number; planDocumentId?: string | null` props; the pane after the Target accounts pane:

```tsx
{projectId ? (
  <div className={styles.workspaceSurface} hidden={surface !== "plan"}>
    <ProjectDocumentSurface active={surface === "plan"} documentId={planDocumentId ?? null} key={projectId} projectId={projectId} refreshToken={planRefreshToken} />
  </div>
) : null}
```

`chat-surface.tsx`: pass `onOpenPlan={shell.openPlan}`, `planRefreshToken={planPrime}`, `planDocumentId={openDocumentId}` (Task 8 sets the latter for gallery-opened documents; `null` here).

- [x] **Step 1: Failing tests** — `chat-surface-params.test.ts`: `?surface=plan` hydrates `surface: "plan"`, `panelOpen: true`; pane params serialize back to `surface: "plan"` with no artifact vocabulary. A new `features/projects/hooks/use-project-document-editor.test.ts` is not possible (hooks need React); instead test the pure reducer pieces if you extract them (`draftAfterChange(drafts, path, base, body)` returns the drafts map with the entry removed when `body === base.body`) — put that pure function in `model/project-document-draft.ts` with a test.
- [x] **Step 2–3: implement.** Run `npm test`, `npm run lint`, `npm run build`.
- [x] **Step 4: Browser check** (on the active Semarang frontend): open a project chat, `?surface=plan` shows the empty state; the tab is keyboard-reachable (Arrow keys move between Gallery / Target accounts / Plan).
- [x] **Step 5: Commit** — `git commit -m "feat(chat-shell): the Plan surface — tab, pane, URL state, and the project document editor on shared markdown pieces"`.

---

### Task 7: Auto-open on write, the plan card click, labels

**Implementation correction, 2026-09-14:** browser QA proved the transcript-snapshot sketch below
cannot distinguish cold history delivered by SSE after `chat.loading` becomes false. It is
superseded by `features/projects/model/plan-write-signal.ts` (`ProjectPlanWriteTracker`) and its
controller wiring. Seed each turn's initial server `lastEventId` before attaching, preserve that
cursor across reconnects, render older events without announcing a write, and announce later
project-document plan parts once per part ID. The shell consumes the controller's monotone
`planWriteRevision` to open/refresh Plan. New submissions attach with cursor zero. This preserves
the original acceptance behavior and uses the existing server contract without a new endpoint.
The regression tests cover late backlog, cursor boundaries, duplicates, reconnect gaps, new
submissions, and unrelated/failed events. The earlier file/interface sketch is retained below as
the design history, not the current implementation.

**Files:**
- Create: `features/chat-shell/model/plan-write-signal.ts` + `plan-write-signal.test.ts`
- Modify: `features/chat-shell/components/chat-surface.tsx` (the effect; `planPrime` state; `onOpenPlan` in the part actions), `features/projects/components/chat-message-part.tsx` (`ChatPartActions.onOpenPlan?: () => void`; the `case "plan"` arm wraps the header in a button when `part.planRef.objectType === "project_document"` and `actions.onOpenPlan` exists: `<PlanTitle>` becomes `<button type="button" className={styles.planOpenButton} onClick={actions.onOpenPlan}>{part.title}</button>`), `features/projects/components/project-flow.module.css` (`.planOpenButton`: inherit typography, `color: var(--clue-ds-color-content-neutral)`, underline on hover, no background/border), `features/projects/model/chat-tool-presentation.ts` (+ test) (`write_project_document: "Write the project plan"`), `features/chat-shell/model/chat-shell-contract.test.ts` (pin the new effect)

**Interfaces:**

```ts
// The signal is the plan PART, not a tool call (re-validation 2026-09-13): the part is emitted at
// turn close from the finalization's domain refs today and from the turn's document rows after
// Lane 1 plan 3, so this rule survives the retirement of write_project_document@1.
export const PLAN_PART_OBJECT_TYPE = "project_document";
export function planWriteToOpen({ transcript, knownPlanPartIds }): string | null
//   returns the id of the newest "plan" part whose planRef.objectType === PLAN_PART_OBJECT_TYPE
//   and whose id is not in knownPlanPartIds, once chat.loading is false; null otherwise.
//   Same shape and invariants as discoveryLaunchToOpen, with the part id in place of the tool call id.
```

The effect in `chat-surface.tsx` copies the discovery effect (lines 341–370) with its own `knownPlanPartIds` ref, calling `shell.openPlan()` and `setPlanPrime(c => c + 1)`; both invariants hold (wait on `chat.loading`; bank every plan part already in the transcript on first load so an old plan does not re-open the tab). Where `ChatPartActions` is built (in `use-project-chat-controller.ts` or `chat-surface.tsx` — find the object literal that supplies `gateFor`), add `onOpenPlan: shell.openPlan`.

- [x] **Step 1: Failing tests** — `plan-write-signal.test.ts` (copy `discovery-launch-signal.test.ts`'s cases, keyed on a `plan` part with `planRef.objectType === "project_document"`; plus: a part with another object type is ignored; a part present on first load is banked, not opened); the contract test asserts `/planWriteToOpen\(\{[\s\S]*?openPlan\(\);\s*setPlanPrime\(/` in `chat-surface.tsx` and that `chat-message-part.tsx` matches `/planRef\.objectType === "project_document"/`; the label test (`write_project_document: "Write the project plan"` stays for transcript history).
- [x] **Step 2–3: implement; run `npm test`, lint, build.**
- [x] **Step 4: Commit** — `git commit -m "feat(chat-shell): the Plan tab opens itself when the agent writes the plan, and the plan card opens it on click"`.

---

**Implementation checkpoint — 2026-09-14:** the founder approved live integration after the
preview. Tasks 6–7 are implemented together; the shared editor session was extracted from
Knowledge rather than duplicating its draft/revision logic. The surface currently selects the
canonical Plan only; `documentId`/Gallery selection lands with Task 8. Server-owned
`project.write` controls editing. Older paginated history is ignored as well as initial history.
The pre-existing historical tool label remains unchanged.

Verification: 2,262 frontend tests pass (Node's `--import tsx` runner avoids the sandbox-blocked
CLI IPC socket), token build, lint (two pre-existing warnings), and Next production build pass.
Semarang alone was migrated from `d639a2de8bd1` to `98775241f1e5`; only its platform API was
restarted, on 8070. Browser empty/read/clean-edit and tab draft retention passed; two browser
saves minted v2/v3 in the disposable project. The store refused a stale save after a separate
v4 write. The browser session then expired. The remaining real-browser reload/conflict,
keyboard/narrow layout, and live plan-part/card walkthrough were pending sign-in at that
checkpoint. Task 8 is not included.

**Resumed verification — 2026-09-14:** the replacement test account reached the correct workspace.
Saved content survived a full browser reload. Browser conflicts preserved drafts through the
latest-version check; Discard adopted the latest document and a subsequent save succeeded.
Arrow/Home/End tab navigation and 720 px / 390 px layouts passed, including long inline code and
code blocks in Preview/Edit. Held, no-model test streams exercised Plan-card clicks, auto-open on
a new document reference, duplicates, and reload backlog. The backlog case caught and verified
the cursor-based correction above. All 2,264 frontend tests, token build, lint (the same two
pre-existing warnings), and production Next build pass. The disposable project/thread are
archived, their append-only audit records retained, both streams completed, and zero fleet tasks
were dispatched. No environment settings or other workspace processes changed.

### Task 8: Project documents in the gallery

**Founder amendment, 2026-09-14:** there is no permanent Plan or Documents tab. A
Gallery-card click or a fresh agent write opens a closable tab named from the returned
document title. Gallery includes the plan as well as ICP/persona files. Design files
also open on fresh creation/update; cold replay must not reopen old tabs. The internal
`surface=plan` alias is retained, with `document=<stable path>` selecting Markdown.
This supersedes the plan-only tab and plan exclusion in the original tasks below.
Backend document kinds, naming rules, paths, permissions and version APIs are unchanged.


**Files:**
- Modify: `features/gallery/model/project-gallery.ts` (`GalleryArtifact` gains `documentKind?: "icp-definition" | "audience-persona" | "project-plan"` and `documentId?: string`), `features/gallery/components/gallery-artifact-card.tsx` (a document card: `file-text` icon in the preview frame, no image; title; `editedLabel`), `features/chat-shell/model/gallery-card-target.ts` (+ test) (`documentKind` present → `{ surface: "plan", documentId }`), `features/chat-shell/components/chat-surface.tsx` (`onOpenGalleryArtifact`: `if (target.surface === "plan") { setOpenDocumentId(target.documentId); shell.openPlan(); return; }`), the gallery feed composition (`app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx`): merge `listProjectDocuments(projectId)` (ICP and persona kinds only; the plan has its own tab) into the feed's cards as document cards, mapped by `toDocumentCard(document): ProjectArtifact`-shaped `GalleryArtifact`
- Test: `gallery-card-target.test.ts` (document → plan surface), `project-gallery.test.ts` (document cards sort by `updatedAt` with the rest; the type filter "Documents" appears only when a document card exists)

- [x] **Step 1: Failing tests. Step 2–3: implement; `npm test`, lint, build.**
- [x] **Step 4: Browser check**: with a project-local ICP present (plan 2's walk), the gallery shows a document card; clicking it opens the Plan surface on that document, with the header naming it ("GI-focused ASCs"), Preview/Edit working, and Save minting a new version (verify with `SELECT version, status FROM brand_knowledge_document WHERE project_id = :p AND path = 'audience/icp-gi-dac.md' ORDER BY version`).
- [x] **Step 5: Commit** — `git commit -m "feat(gallery): project ICP and persona documents appear as document cards and open on the document surface"`.

---


## Self-review

- Coverage of spec §4.3's frontend half: model/repository/BFF (T4), shared markdown pieces (T5), surface/tab/pane/editor (T6), auto-open + card click + labels (T7), gallery document cards (T8). ✔
- Placeholder scan: none beyond the parent's. ✔


**Task 8 acceptance, 2026-09-14:** all three document kinds appear in Gallery and route by
stable path to separate named tabs. One shared list read supplies the Gallery and surfaces;
failed reads are explicit. Native editor sessions persist through tab switching/closing.
Real browser saves and artifact/DB revisions verified all kinds. Controlled held streams
verified exact persona-ref auto-open, card-click opening, duplicate delivery and cold replay.
No model calls or fleet execution. The suite now has 2,270 passing tests; tokens/lint/build
pass. New chat-card visual feedback is tracked separately with an isolated compact preview.
