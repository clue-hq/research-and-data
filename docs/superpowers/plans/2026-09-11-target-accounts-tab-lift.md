# Target accounts tab — lift from the dummy frontend (2026-09-11)

**Spec (authority):** the dummy frontend at
`/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`, commit `e3bcea7`
("feat(accounts): add project target accounts and shared previews"), and its contract note in
`docs/api-contracts/accounts.md` § "Project Target Accounts prototype". The dummy is presentation
truth: markup, class names, copy and stylesheets are copied, never redesigned. Only the data
seams change, and one behaviour changes by founder ruling (below).

**Founder rulings binding this plan (2026-09-11):**
1. Lift the tab, the project-scoped table, the preview drawer and "Open as page" exactly as the
   dummy has them. "Open as page" always navigates to the canonical workspace route
   `/accounts/:accountId`.
2. **"Add accounts" writes real memberships through the existing bulk action**
   (`addAccountsToProject` → `POST /accounts/bulk-actions/add-to-project`), never local state
   only. The dummy's local-only picker is the one behaviour NOT lifted.
3. No backend change is expected: the accounts read already takes `projectId` and returns the
   project's members (ruling 8′ makes discovered accounts members of their launching project).
   If a task finds a backend change is needed, it stops and reports NEEDS_CONTEXT.
4. Frontend gates for this lift: `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build`
   from `apps/frontend`. All four must pass before the branch is finished.

**Starting state of the tree (already done by the controller; do not redo):**
- Applied cleanly from the dummy commit: `account-checkbox.tsx`, `account-detail-primitives.tsx`,
  `account-preview-drawer.tsx`, `accounts-filter-panel.module.css`, `accounts-toolbar.tsx`.
- Copied verbatim from the dummy (untracked, not yet adapted): `components/project-target-accounts.tsx`,
  `components/project-account-preview.tsx`, `components/project-account-dialogs.tsx`,
  `components/project-accounts.module.css`, `components/accounts-toolbar.module.css`,
  `model/project-accounts.ts` (+ test), `data/project-accounts.repository.ts` (+ test),
  `src/app/api/projects/[projectId]/accounts/route.ts`, `src/app/api/accounts/[accountId]/route.ts`
  (+ test), `src/app/(protected)/projects/[projectId]/accounts/page.tsx` (redirect).
- NOT applied (diverged; must be done by hand): `accounts-table.tsx`,
  `hooks/use-accounts-screen-controller.ts`, and every chat-shell file.
- Present already: `public/icons/projects/target-accounts.svg`, `chevron-right.svg`, `search.svg`,
  and their entries in `features/projects/config/project-icon-sources.ts`.

**Global constraints**
- Dummy is presentation truth. Where a dummy file is copied, keep its JSX and class names; adapt
  imports and data calls only. Never invent UI.
- Integrate at the repository seam: components call repositories; no `fetch` of backend paths
  from components except the two BFF routes the dummy itself uses (`/api/projects/:id/accounts`,
  `/api/accounts/:id`).
- Our seams (use these, not the dummy's): `getAccounts` in `data/accounts.repository.ts` already
  forwards `projectId` and follows the backend's cursor pages, returning the whole list with
  `meta.nextCursor: null`; `getAccountDetails(accountId)` in `data/account-details.repository.ts`;
  `readAccountBulkCapabilities()` in `data/bulk-capabilities.repository.ts`;
  `addAccountsToProject({ accountIds, idempotencyKey, projectId })` in
  `data/bulk-actions.repository.ts`; `getWorkspaceProfile()` in
  `data/workspace-profile.repository.ts` (the platform has no settings feature — the dummy's
  `getSettingsWorkspace().profile` becomes this).
- `useAccountsScreenController(initialAccounts, bulkCapabilities, submitAddToProject?)` is our
  signature; the dummy's `(initialAccounts, project?)` is NOT adopted. Extend ours with a trailing
  optional `options?: { project?: AccountProject }` and keep every existing export.
- The chat shell's surface vocabulary lives in `hooks/use-editor-shell-controller.ts`
  (`EditorShellSurface`), `model/chat-shell.ts` (`ChatShellSurface`), and
  `model/chat-surface-params.ts` (URL parse/serialize). All three gain `"target-accounts"`.
- Tests are `node --test` via `npm test` (`*.test.ts`, no DOM). New behaviour gets a test where the
  dummy had one; adapted tests keep the dummy's assertions where the seam allows.
- No `.env`/backend edits. No Claude attribution in commits. Commit per task on `track-r4`.

---

## Task 1 — Data seams: model, repository, BFF routes, redirect page

**Files:** `apps/frontend/src/features/accounts/model/project-accounts.ts` (+ `.test.ts`),
`apps/frontend/src/features/accounts/data/project-accounts.repository.ts` (+ `.test.ts`),
`apps/frontend/src/app/api/projects/[projectId]/accounts/route.ts`,
`apps/frontend/src/app/api/accounts/[accountId]/route.ts` (+ `.test.ts`),
`apps/frontend/src/app/(protected)/projects/[projectId]/accounts/page.tsx`.

1. `model/project-accounts.ts`: replace the `SettingsWorkspaceSchema.shape.profile` import with our
   `WorkspaceProfile` shape — find the Zod schema for it (grep `workspace-profile` under
   `features/accounts/model`); if only a TS type exists, define `profile` as a Zod object matching
   that type's fields exactly. Add `bulkCapabilities: AccountBulkCapabilitiesSchema` to
   `ProjectAccountsResponseSchema` (from `model/bulk-actions.ts`) — the project table's controller
   needs it. Keep `accountsForProject`, `paginateAccounts`, `accountPageSizes` verbatim.
2. `data/project-accounts.repository.ts`: keep `readAccountDirectory` and
   `getProjectAccountDirectory` as copied (our `getAccounts` satisfies the `list` shape — confirm
   its return carries `data` and `meta.nextCursor`; if the name differs, adapt the import only).
3. `api/projects/[projectId]/accounts/route.ts`: compose `getProjectAccountDirectory(projectId)`,
   `getWorkspaceProfile()` and `readAccountBulkCapabilities()`; respond
   `{ ...directory, profile, bulkCapabilities }` with `Cache-Control: no-store`; keep the dummy's
   502 envelope on failure. Session/workspace scoping comes from the repositories (they use the BFF
   seam already) — do not add auth code here.
4. `api/accounts/[accountId]/route.ts`: keep as copied; its test as copied, adapted to our
   `getAccountDetails` signature if the mock shape differs.
5. Redirect page: keep as copied (imports `projectTargetAccountsHref`, which Task 3 adds — until
   then, import from `@/features/chat-shell/model/chat-shell-routes` and add that one-line helper
   in this task so the page type-checks: `projectTargetAccountsHref(projectId, threadId?)` =
   `projectChatHref(projectId, threadId ?? "thread-primary", { surface: "target-accounts" })`).
   Also add the dummy's assertion for it to `chat-shell-routes.test.ts`.
6. Run `npm test` and `npx tsc --noEmit` (tsc may still fail on the not-yet-adapted components from
   Task 2; report which errors are Task 2's — those are expected).

## Task 2 — Account components: table, controller hook, dialogs, real membership write

**Files:** `apps/frontend/src/features/accounts/components/accounts-table.tsx`,
`apps/frontend/src/features/accounts/hooks/use-accounts-screen-controller.ts`,
`apps/frontend/src/features/accounts/components/project-target-accounts.tsx`,
`apps/frontend/src/features/accounts/components/project-account-dialogs.tsx`,
`apps/frontend/src/features/accounts/components/project-account-preview.tsx`.

The dummy's hunks for the table and the hook are in the dummy commit
(`git -C <dummy> show e3bcea7 -- src/features/accounts/components/accounts-table.tsx
src/features/accounts/hooks/use-accounts-screen-controller.ts`). Apply their INTENT by hand onto
our versions, which diverged for the live backend (bulk capabilities, `selectable` rows, chat
handoff):

1. `accounts-table.tsx`: add the dummy's optional `onOpenAccount?: (account: Account) => void` and
   `label?: string` props and their use (row click opens the preview; the aria label), keeping
   our `selectable` prop and `AccountRow[]` typing. Where the dummy passes `Account` and ours has
   `AccountRow`, keep ours.
2. `use-accounts-screen-controller.ts`: add trailing `options?: { project?: AccountProject }`;
   compute `scopedAccounts` (rows filtered to the project when given, else all rows) and use it
   where the dummy used it (search/filter/sort input, column definitions); add `addAccounts(
   accounts: Account[])` (the dummy's body: append rows not already present, stamping the project
   membership, and widen column order/widths/visibility) and `toggleAccounts(accounts)`; keep
   `toggleAllVisibleAccounts` as a call to `toggleAccounts(visibleAccounts)`; export `accounts:
   scopedAccounts`, `addAccounts`, `toggleAccounts` alongside every existing export.
3. `project-target-accounts.tsx`: call our controller as
   `useAccountsScreenController(accountsForProject(data.accounts, projectId), data.bulkCapabilities,
   undefined, { project })`. **Ruling 2:** the dialog's `onAdd` becomes an async handler that (a)
   calls `addAccountsToProject({ accountIds, idempotencyKey: crypto.randomUUID(), projectId })`,
   (b) on success applies `controller.addAccounts(accounts)` for the rows and re-fetches
   `/api/projects/:id/accounts` so membership reflects the backend, (c) on failure shows the
   dummy's existing error affordance (reuse the `role="alert"` block pattern; no new UI) and leaves
   rows unchanged. Keep everything else verbatim.
4. `project-account-dialogs.tsx` / `project-account-preview.tsx`: keep verbatim unless an import
   differs; `AccountPreviewFrame`/`AccountPreviewContent` are exported by our
   `account-preview-drawer.tsx` after the applied hunk — confirm.
5. Tests: `model/project-accounts.test.ts` and `data/project-accounts.repository.test.ts` as
   copied (adapt imports). Add one `node --test` for the hook's `addAccounts` stamping the project
   membership if the hook is testable without DOM (it uses React state — if not, skip and say so).
6. `npm test`, `npm run lint`, `npx tsc --noEmit` — the accounts feature must be clean.

## Task 3 — Chat shell: surface, tab, stage, routing

**Files:** `apps/frontend/src/features/chat-shell/hooks/use-editor-shell-controller.ts`,
`apps/frontend/src/features/chat-shell/model/chat-shell.ts`,
`apps/frontend/src/features/chat-shell/model/chat-surface-params.ts` (+ test if present),
`apps/frontend/src/features/chat-shell/components/artifact-tabs.tsx`,
`apps/frontend/src/features/chat-shell/components/artifact-stage.tsx`,
`apps/frontend/src/features/chat-shell/components/chat-shell.module.css`,
`apps/frontend/src/features/chat-shell/components/chat-surface.tsx`.

The dummy's hunks: `git -C <dummy> show e3bcea7 -- src/features/chat-shell` (tabs, stage, css,
routes, model). Ours composes the shell through `chat-surface.tsx` + `use-editor-shell-controller.ts`
instead of the dummy's `chat-shell-view.tsx` + `use-chat-shell-controller.ts`; carry the intent:

1. `EditorShellSurface` and `ChatShellSurface` gain `"target-accounts"`. Reducer: action
   `{ type: "open-target-accounts" }` → `{ ...state, editing: false, panelOpen: true, surface:
   "target-accounts" }`; controller returns `openTargetAccounts`. Opening an artifact or the gallery
   leaves the surface as today.
2. `chat-surface-params.ts`: `parseChatSurface("target-accounts")` → `"target-accounts"`; the
   serializer writes `surface=target-accounts` for that surface (the shareable route the dummy
   documents: `/projects/:id/chats/:chatId?surface=target-accounts`). Panel-open rule unchanged.
3. `artifact-tabs.tsx`: the dummy's tab verbatim (`onOpenTargetAccounts?` prop; button with
   `aria-selected`, `role="tab"`, `ProjectIcon name="target-accounts" size={12}`, label
   "Target accounts"), rendered after the Gallery tab inside the same segment.
4. `artifact-stage.tsx`: new props `onOpenTargetAccounts`, `projectId`, `projectTitle`; pass the
   handler to `ArtifactTabs`; render the dummy's block —
   `<div className={styles.workspaceSurface} hidden={surface !== "target-accounts"}>
   <ProjectTargetAccounts active={surface === "target-accounts"} key={projectId} projectId=…
   projectTitle=… /></div>` — and wrap the existing artifact/gallery output in
   `<div className={styles.workspaceSurface} hidden={surface === "target-accounts"}>` so the table
   stays mounted (the dummy's "preserved table state" rule). `showingArtifact` stays false on the
   new surface.
5. `chat-shell.module.css`: the dummy's `.workspaceSurface` rules verbatim (display flex, flex 1,
   min sizes 0, overflow hidden; `[hidden]` → display none; `> *` flex 1). The dummy's other css
   hunk (`.shellArtifactMaximized` / `.artifactTabs` padding at the responsive breakpoint) is
   lifted too if the selectors exist in ours; otherwise report it as ⚠️ not applicable.
6. `chat-surface.tsx`: pass `onOpenTargetAccounts={shell.openTargetAccounts}`, `projectId`, and
   `projectTitle={workspace.title}` (or the field our `ProjectWorkspace` carries) to
   `ArtifactStage`; the dock rule must treat `"target-accounts"` like `"gallery"` (rail open, no
   editor) — check `model/chat-dock.ts` and add the case with a test if that module has tests.
7. `npm test`, `npm run lint`, `npx tsc --noEmit`, then `npm run build`.

## Task 4 — Contract note, parity check, live check

**Files:** `apps/frontend/docs/api-contracts/accounts.md`, and no code unless the check fails.

1. Add the dummy's "Project Target Accounts" section to our `accounts.md`, edited for the two
   seam differences: the BFF route composes our workspace profile and bulk capabilities, and
   "Add accounts" writes membership through the bulk action (ruling 2) — the dummy's local-only
   sentence is replaced, not kept.
2. `npm test && npm run lint && npx tsc --noEmit && npm run build` all green; report counts.
3. Live check on the running stack (`./scripts/dev_stack_san_salvador.sh status` must show all
   UP; if the frontend needs the new routes compiled, it hot-reloads): with `curl`, confirm
   `GET http://localhost:3020/projects/prj_82aef3f543395a72804afb9635d969a1/accounts` answers a
   redirect to `/projects/…/chats/…?surface=target-accounts`. The signed-in walk (tab, table,
   preview, Open as page, Add accounts) is the founder's; list exactly what to click.
