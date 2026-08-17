# Lane 1 / Phase R — Chat Route Migration Implementation Plan

> **Naming note:** this is the first executable phase of Lane 1 (the route
> substrate both other lanes fork from). It is named Phase R (routes) to avoid
> colliding with the accounts-parity lane, which earlier discussion sometimes
> called "Phase A". Lane map: Lane 1 = this plan → Phase C (chat chrome);
> Lane 2 = the W-phases (website editor, separate plan); Lane 3 = co-founder
> accounts parity (separate governance doc).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move chat from the legacy `?thread=` query param to the ratified explicit route `/projects/{projectId}/chats/{chatId}`, rendering OUR production chat, with `/projects/{id}` as the redirect absorber — zero visual change.

**Architecture:** Lift the dummy branch's dependency-free route-helper module (amended: no fixture fallback), add the chats route segment under the `(protected)` group rendering the existing `ProjectWorkspaceShell`, convert `/projects/{id}` and `/projects/{id}/gallery` to their ratified redirect semantics, flip every frontend and backend href emitter through the helper, and adopt the `?surface=/edit=/selection=` pane-state vocabulary (parse now, editor wiring later). Wiring is untouched: same repositories, same SSE stream, same gates.

**Tech Stack:** Next.js App Router (apps/frontend, npm, node:test via `tsx --test`), FastAPI chat router (`platform/api/clue_api/chat/`, pytest via `make check`).

**Spec:** Founder rulings R1–R8 (2026-08-17) + the tri-area diff synthesis, both recorded in `_memory/2026-08-17-frontend-tri-diff-synthesis.md`. Source-of-truth reference tree: `/tmp/clue-frontend-tip` (clue-hq/clue-frontend@codex/chat-shell, c7f2bc5) — re-clone with `gh repo clone clue-hq/clue-frontend /tmp/clue-frontend-tip -- --depth 50 -b codex/chat-shell` if absent.

## Global Constraints

- **R1:** `/projects/{id}` adopts redirect semantics (with `?thread=` → server redirect to the chats route; threadless → render workspace, which client-canonicalizes the URL to `/chats/{resolved}`).
- **R2:** Pane-state vocabulary is `?surface=` (`chat|gallery|web|ad`) + `?edit=1` + `?selection=`. **`?artifact=` is superseded and must not be introduced.**
- **R3:** `/projects/{id}/gallery` is a compat redirect. The lifted helper's `"thread-primary"` fixture fallback is deleted; `projectGalleryHref` requires a real thread id.
- **R10 default:** thread canonicalization uses `router.replace` (never `push` — back-button trap); `THREAD_NOT_FOUND` keeps the existing in-pane alert.
- Wiring is ours everywhere: the chats route renders `ProjectWorkspaceShell`; never lift the dummy's route bodies (their `getProjectWorkspace` is fixture-non-null; ours returns `null` in HTTP mode).
- Zero user-visible visual change in this phase. No new UI elements (parity constitution).
- Frontend gate: `cd apps/frontend && npm test && npm run lint && npm run build`. Backend gate: `make check` (or targeted `pytest` for the chat router). Commit locally at every task boundary; **never push**; no AI attribution.
- Our Zod href guards (`z.string().startsWith("/projects/")` in `model/sidebar-project.ts:43,47` and `model/project-workspace.ts:245,251,264`) accept both old and new shapes — frontend/backend landing order is free, but both land in this phase.

---

### Task R-1: Lift the route-helper model (amended)

**Files:**
- Create: `apps/frontend/src/features/chat-shell/model/chat-shell-routes.ts` (from `/tmp/clue-frontend-tip/src/features/chat-shell/model/chat-shell-routes.ts`)
- Create: `apps/frontend/src/features/chat-shell/model/chat-shell-routes.test.ts` (from source, amended)

**Interfaces:**
- Produces: `projectChatHref(projectId: string, chatId: string, query?: ChatShellRouteQuery): string` → `/projects/{enc}/chats/{enc}[?…]`; `projectArtifactHref(projectId, artifactId, query?)` → `/projects/{enc}/artifacts/{enc}[?…]`; `projectGalleryHref(projectId: string, threadId: string)` → `projectChatHref(projectId, threadId, { surface: "gallery" })`; `type ChatShellRouteQuery = Record<string, string | undefined>`. `withQuery` drops `undefined` AND `""` values.

- [ ] **Step 1:** Copy both files verbatim from the source tree.
- [ ] **Step 2:** Apply the single amendment — `projectGalleryHref` loses its `"thread-primary"` default:

```ts
export function projectGalleryHref(projectId: string, threadId: string): string {
  return projectChatHref(projectId, threadId, { surface: "gallery" });
}
```

- [ ] **Step 3:** Amend the test: replace the `thread-primary`-default assertions with an explicit-thread assertion (`projectGalleryHref("campaign one", "t1")` → `/projects/campaign%20one/chats/t1?surface=gallery`); keep the encoding, `edit=1&surface=web`, artifact-href, and empty-query (`{edit: undefined, surface: ""}` → bare path) assertions unchanged.
- [ ] **Step 4:** Run: `npx tsx --test src/features/chat-shell/model/chat-shell-routes.test.ts` → PASS.
- [ ] **Step 5:** Commit: `feat(routes): lift chat-shell route helpers; fixture thread fallback removed (R3)`.

### Task R-2: The chats route renders our production chat

**Files:**
- Create: `apps/frontend/src/app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx`
- Modify: `apps/frontend/src/features/projects/components/project-workspace-shell.tsx` (remount key)

**Interfaces:**
- Consumes: `ProjectWorkspaceShell` (`initial: {focusPane?: "artifacts"; handoffId?: string; threadId?: string}`, `projectId`, `workspace`), `getProjectWorkspace` (returns `ProjectWorkspace | null` in HTTP mode — must flow through as today).
- Produces: the canonical chat URL; `?surface=gallery` → `focusPane: "artifacts"`; `?surface=web|ad`, `?edit=`, `?selection=` parsed and deliberately unused (reserved for the editor lane per R2 — note this in a comment).

- [ ] **Step 1:** Write the page (mirror the existing `[projectId]/page.tsx` fetch pattern exactly — server component, awaits params/searchParams, fetches workspace which may be null):

```tsx
import { getProjectWorkspace } from "@/features/projects/data/project-workspace.repository";
import { ProjectWorkspaceShell } from "@/features/projects/components/project-workspace-shell";

interface ProjectChatPageProps {
  params: Promise<{ chatId: string; projectId: string }>;
  searchParams: Promise<{ edit?: string; handoff?: string; selection?: string; surface?: string }>;
}

export default async function ProjectChatPage({ params, searchParams }: ProjectChatPageProps) {
  const [{ chatId, projectId }, query] = await Promise.all([params, searchParams]);
  // R2: surface/edit/selection are the ratified pane-state vocabulary. Only
  // surface=gallery is wired here; web|ad/edit/selection are reserved for the
  // design-editor split view and intentionally unused in Phase R.
  const workspace = await getProjectWorkspace(projectId);
  return (
    <ProjectWorkspaceShell
      initial={{
        focusPane: query.surface === "gallery" ? "artifacts" : undefined,
        handoffId: query.handoff,
        threadId: chatId,
      }}
      projectId={projectId}
      workspace={workspace}
    />
  );
}
```

- [ ] **Step 2:** Simplify the remount key in `project-workspace-shell.tsx`: remove `threadId` from the composed `key` (the path segment now owns thread-change remounts; a retained threadId key would double-remount and close SSE attachments). Keep `workspace.id` and `handoffId` parts. Read the file first; the key is the `key={...}` expression noted in `_memory/2026-08-17-frontend-tri-diff-synthesis.md`.
- [ ] **Step 3:** `npm run build` → the route appears in the route list. Manually verify in dev: `/projects/<id>/chats/<threadId>` renders the workspace with that thread active (fixture mode: use a fixture thread id from `chat.fixture.ts`).
- [ ] **Step 4:** Commit: `feat(routes): canonical /projects/{id}/chats/{chatId} route renders production chat (R1/R2)`.

### Task R-3: Controller URL writers go path-based

**Files:**
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` (`replaceThreadInRoute` ~:221-227; `selectThread` ~:827)
- Test: existing `use-project-workspace-controller.test.ts` exercises the handoff-cleanup interleaving — extend, don't replace.

**Interfaces:**
- Consumes: `projectChatHref` from Task R-1.
- Produces: `replaceThreadInRoute(threadId)` → `router.replace(projectChatHref(projectId, threadId, currentQueryMinusThread))` (canonicalization, R10: replace, never push); `selectThread(threadId)` additionally performs `router.push(projectChatHref(projectId, threadId, currentQuery))` (user-initiated switch = navigation with history).

- [ ] **Step 1:** Read both functions and the surrounding query handling. Write/extend a failing test asserting: canonicalization produces the path-based URL via `replace`; an explicit `selectThread` produces it via `push`; the `?handoff=` cleanup (which uses `usePathname()`) composes with the new pathname without resurrecting `?thread=`.
- [ ] **Step 2:** Implement: both writers build URLs through `projectChatHref`; `thread` is never written as a query param again; preserved query keys (`handoff`, `surface`, etc.) pass through the helper's query argument.
- [ ] **Step 3:** `npm test` → all green (the race landmine test included).
- [ ] **Step 4:** Commit: `feat(routes): thread selection and canonicalization write the chats path (R1, R10)`.

### Task R-4: Absorber + gallery compat redirects

**Files:**
- Modify: `apps/frontend/src/app/(protected)/projects/[projectId]/page.tsx`
- Modify: `apps/frontend/src/app/(protected)/projects/[projectId]/gallery/page.tsx`

- [ ] **Step 1:** `[projectId]/page.tsx`: with `?thread=` → immediate server `redirect(projectChatHref(projectId, query.thread, { edit: query.edit, handoff: query.handoff, selection: query.selection, surface: query.surface }))` **before any fetch** (a redirect stub must not fetch). Threadless → keep today's body (fetch workspace, render `ProjectWorkspaceShell`); the Task R-3 canonicalization then rewrites the URL to `/chats/{resolved}` client-side (R1's threadless semantics).
- [ ] **Step 2:** `gallery/page.tsx` becomes compat-only:

```tsx
import { redirect } from "next/navigation";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";

interface ProjectGalleryPageProps {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ thread?: string }>;
}

export default async function ProjectGalleryPage({ params, searchParams }: ProjectGalleryPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  if (query.thread) redirect(projectChatHref(projectId, query.thread, { surface: "gallery" }));
  redirect(`/projects/${encodeURIComponent(projectId)}`);
}
```

- [ ] **Step 3:** `npm run build`; dev-verify: `/projects/<id>?thread=<t>` lands on `/projects/<id>/chats/<t>`; `/projects/<id>/gallery?thread=<t>` lands on `…/chats/<t>?surface=gallery`; threadless `/projects/<id>` still renders and self-canonicalizes.
- [ ] **Step 4:** Commit: `feat(routes): /projects/{id} absorber + gallery compat redirect (R1, R3)`.

### Task R-5: Frontend emitter flips + test updates

**Files (the complete `?thread=` sweep — no others exist):**
- Modify: `apps/frontend/src/features/projects/hooks/use-add-to-chat-controller.ts:151` → `router.push(projectChatHref(projectId, threadId, { handoff: handoff.handoffId }))`
- Modify: `apps/frontend/src/features/projects/data/chat-threads.repository.ts:137` (fixture `create()` href)
- Modify: `apps/frontend/src/features/projects/data/project-home.repository.ts:74,81` (fixture hrefs)
- Modify: `apps/frontend/src/features/projects/data/chat.fixture.ts:29,39`
- Modify: `apps/frontend/src/features/projects/data/sidebar-projects.fixture.ts` (5 conversation hrefs + the gallery-flavored one; 3 project hrefs stay `/projects/{id}` — the absorber handles them)
- Modify: `apps/frontend/src/features/accounts/components/account-workspace-screens.tsx:233` (route through the helper for consistency; stays a project link)
- Tests: `data/sidebar-projects.repository.test.ts:36`, `data/project-home.repository.test.ts:80,93,128`, `data/chat-repositories.test.ts:104`, `model/chat-schemas.test.ts:92` — update the asserted shapes to `/projects/{p}/chats/{t}`.

- [ ] **Step 1:** Update the four test files first to assert the new shape; run `npm test` → they FAIL against the old emitters.
- [ ] **Step 2:** Flip the emitters (all fixture hrefs become `projectChatHref(...)` calls or the literal new shape, matching each file's existing style).
- [ ] **Step 3:** `npm test && npm run lint && npm run build` → green.
- [ ] **Step 4:** Commit: `feat(routes): all thread-href emitters produce the chats path`.

### Task R-6: Backend href flip + contract docs

**Files:**
- Modify: `platform/api/clue_api/chat/schemas.py:299` — the shared thread-href helper → `return f"/projects/{project_id}/chats/{thread_id}"`
- Modify: `platform/api/clue_api/chat/router.py:903` (bootstrap `href` — uses the shared helper if it doesn't already), `:977` (sidebar conversation `href`). `:912` (project `href` `f"/projects/{project_id}"`) **stays** — the absorber owns it.
- Modify: any backend tests pinning the old string (`grep -rn "?thread=" platform/api` to find them).
- Modify: `apps/frontend/docs/api-contracts/projects.md` — replace the six `?thread=` contract mentions (lines ~900, 913, 1017, 1270, 1407 + gallery semantics ~176) with the canonical-routes table adopted from the dummy repo's `docs/api-contracts/projects.md:301-315` (including its "`?thread=` must not be emitted by new UI" rule) and note the `(protected)`-shell paragraph (~425-427) is unchanged.

- [ ] **Step 1:** Grep backend tests for the old shape; update expectations to the new shape first → targeted `pytest` FAILS.
- [ ] **Step 2:** Flip the three emitter sites (keep `:912`).
- [ ] **Step 3:** Targeted `pytest` on the chat router → PASS; then `make check`.
- [ ] **Step 4:** Amend the contract doc; record the R2 supersession (`?artifact=` → `?surface=`) in the doc's decision log.
- [ ] **Step 5:** Commit: `feat(routes): backend thread hrefs emit the chats path; contract docs adopt canonical routes (R1-R3)`.

### Task R-7: Supersession amendments + end-to-end browser verification + close-out

**Files:**
- Modify: `docs/superpowers/plans/2026-08-17-website-editor-integration.md` — W0.4/editor-surface `?artifact=` mentions annotated: superseded by R2 (`?surface=web|ad` + `/artifacts/{id}` path identity).
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx` header comment — same supersession note (comment-only change).
- Modify: `_memory/2026-08-17-frontend-tri-diff-synthesis.md` — Phase R close-out entry.

- [ ] **Step 1:** Apply both supersession annotations.
- [ ] **Step 2:** Browser verification with the gstack browse skill (dev server, fixture mode), all of: old `?thread=` deep link redirects and chat renders with the right thread; sidebar conversation click navigates to the chats path; add-to-chat handoff lands on the chats path with `?handoff=` intact and cleaned up after restore; thread canonicalization (`router.replace`) leaves no `?thread=` residue and back-button does not trap; `surface=gallery` shows the artifacts pane; SSE transcript/gates still stream (open a fixture thread with turns).
- [ ] **Step 3:** Full gates: frontend `npm test && npm run lint && npm run build`; root `make check`.
- [ ] **Step 4:** Memory close-out; commit: `feat(routes): phase R complete — chats path canonical end to end`.

**Phase R exit gate:** every chat entry point (sidebar, home bootstrap, add-to-chat, deep links old and new) lands on `/projects/{id}/chats/{chatId}` rendering the unchanged production chat; `?thread=` survives only as a redirect; both check gates green; zero visual change.

---

## Sequencing

R-1 → R-2 → R-3 → R-4 → R-5 → R-6 → R-7, strictly (each consumes the previous task's interface). Phase C (chat chrome adoption) starts only after the R-7 exit gate. W1 (editor foundation) may run in a parallel worktree throughout — it shares no files with this plan.
