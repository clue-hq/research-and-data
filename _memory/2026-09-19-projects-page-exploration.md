# 2026-09-19 — Projects directory + project home (`/projects`, `/projects/{id}`): exploration before integration planning (no code changed)

**Lane:** worktree `fredericton`, branch `research-streaming-v3` at `21e3ef1e9`, target `integration/design-improvement`.
Exploration only. No `.env`, no lane dev-stack wrapper and no lane DB exist in this worktree yet
(the attachment "Transcript of .env ports change" named in the prompt is not on disk under
`.context/attachments/`).

## Presentation truth (the dummy)

- `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain`, commit `9fc902a`
  "feat(projects): build project directory and memory home" (26 files, +852). Docs:
  `docs/api-contracts/projects.md` §"Projects home and directory (2026-09-06)" and
  `docs/figma/projects-chat-flow.md` §"Projects directory and project home".
- Routes: `/projects` → `ProjectsScreen` (directory); `/projects/{id}` → `ProjectsScreen projectId`
  (project home; `?thread=` still redirects to the chat). Nav label flips "Project" → "Projects".
- Directory: two-column card grid (title link, description, updated date, pin glyph), header
  search + sort (Last updated / Date created / Alphabetical) + "New project"; card menu Pin / Edit
  details / Archive; footer link toggles the "Archived projects" view; 12-per-page client paging.
- Home: breadcrumb, title + description, pin + menu; archived notice with Restore; left column =
  `ChatComposer` (entities=[]) + "Recent chats" rows (title link, status badge, date); right rail =
  Instructions (single text, ≤12000) and Memory (notes ≤4000, optional `sourceChatId` that must be a
  chat of the same project, "Added by you" otherwise; edit/remove dialog).
- Data: ONE aggregate `ProjectDirectorySchema` (projects with conversations+messages, accounts,
  artifacts, instructions, memory; plus accountCatalog, models) behind a client `useSyncExternalStore`
  store; preview mode = localStorage (`clue:project-directory:preview:v1`); HTTP mode = proposed
  `GET /api/v1/projects/directory` + `POST /api/v1/projects/directory/commands` (13 command kinds:
  create/details/pin/expand/archive/archive-chats/chat/message/rename-chat/accounts/instructions/
  memory/remove-memory), client-minted ids as idempotency keys. Rules in `applyProjectCommand`:
  archived ⇒ read-only except archive/pin/expand; archive blocked while a chat is `running`;
  `updatedAt` bumps on every command except pin/expand. The dummy's own doc says the aggregate is a
  bounded handoff and production should use cursor reads under authenticated `/frontend/v1`.
- Shared-file changes: sidebar controller consumes the same store; chat shell renders saved user
  messages (no generation); `EditProjectDialog` removal button reads "Archive project".
- Components the lift needs that exist here: `AccountFilterSelect`, `SidebarFigmaIcon`
  (`sidebar-pin/-archive/-edit-project/-ellipsis` SVGs present), `ProjectIcon` (search/edit/plus/
  close), `SidebarConversationStatus`, base-ui Dialog/Menu. NOT here: `src/components/chat/ChatComposer`
  (the dummy's newer composer; this repo's Home uses `ProjectComposer`).

## This repo today

Frontend (`apps/frontend`):
- `src/app/(protected)/projects/page.tsx` = empty white `<main>` (nav link exists, page is blank).
- `src/app/(protected)/projects/[projectId]/page.tsx` = Phase-R legacy absorber (ruling R1): `?thread=`
  server-redirects; threadless renders `ProjectWorkspaceShell` which canonicalizes to the default
  thread's chats route. `getProjectWorkspace` returns `null` in HTTP mode (fixture-only server read).
- Sidebar: `GET /api/v1/projects/sidebar` (BFF `/api/clue`), `SidebarProjectSchema` has `pinned`/
  `expanded` but the wire transform hard-codes both false; controller: rename real (HTTP), pin
  fixture-only, "Archive chats" = per-thread loop, expand = local state; reload via
  `useProjectCatalogInvalidation`.
- `ProjectWorkspaceSchema` (project shell): id/title/brandId/productId/status/createdAt/entities/
  composerCapabilities/agentProfiles — no description, no pinned, no updatedAt.
- Home (`/`) creates a project + first thread + first turn atomically via `POST /api/v1/projects`
  with Idempotency-Key, brand, message, context_refs, attachment_refs, agent_profile_id.
- No memory feature anywhere in the frontend (memory only appears in the dev-lens inspector).

Backend:
- `project` row (`98422adaaa38`): project_id, workspace_id, brand_id, product_id?, name, status
  ∈ {draft, active, archived}, created_at. NO description, NO pinned, NO updated_at, NO kind.
  Spine (`libs/clue-spine/clue_spine/spine.py`): create/get/get_for_workspace/set_project_name/
  set_project_name_if_untitled/confirm_project_product. `UNTITLED_PROJECT_NAME = "Untitled project"`.
- Routes (`chat/router.py`): `POST /projects` (Home bootstrap only: needs message + brand; born
  `active`, name "Untitled project", namer renames after the first reply), `GET /projects/sidebar`
  (active-only, created_at DESC keyset, 50/100), `GET /projects/{id}` (shell), `PATCH /projects/{id}`
  (`rename_project@1`, title only, `pinned` rejected 422), threads create/list(?status=active|archived)/
  patch(title, pinned)/archive, design-artifacts, composer-context. Documents:
  `GET/PUT /frontend/v1/projects/{id}/documents[/{doc}]`.
- Governed project tools: `rename_project@1` (ungranted, human-only) is the ONLY project-row
  mutation. No create-empty, no archive/restore, no pin, no description.
- The only `archived` writer: `onboarding_synthesis_wiring.ensure_onboarding_project` — the per-brand
  SYSTEM project `prj_onb_<24hex>` named "Onboarding · <brand>", born `archived`, a scope anchor "never
  something a marketer opens". An "Archived projects" view would list it unless excluded.
- Accounts: `project_account (workspace_id, project_id, account_entity_id, added_via, added_at)`;
  reads `GET /frontend/v1/accounts?projectId=` and tool `read_project_accounts@1`; write via
  `POST /frontend/v1/accounts/bulk-actions/add-to-project` (active projects only).
- Project documents: `brand_knowledge_document.project_id` (migration `b953bf11e2a9`), folder
  `project`, kinds incl. `project-plan`; any markdown path under the `project/` mount is a document;
  human edits through the PUT route, agent through `write_file` on the versioned mount; the tree is
  compiled into the turn as the `project_library_index` card. Nearest existing home for
  "Instructions" = a project document (e.g. `project/instructions.md`).
- Scoped memory (Doc M, `subsystems/memory/clue_memory`, migration `8aba77245267`): `memory` rows
  with `scope_type='project'` + `scope_project_id`, `type ∈ {preference, behavioral_learning}`,
  `provenance_class ∈ {user_stated (born active), edit_distilled, agent_observed (born proposed)}`,
  status lifecycle, `memory_event` journal, DSAR verbs. Write seam rejects fact-shaped bodies
  (`FACT_SHAPED` → claim store) and bodies quoting personal claims; every write runs the LLM
  reconcile judge (`CLUE_MEMORY_RECONCILE_MODEL`, a paid call). Production Head-of-ABM turns
  already assemble project-scoped PREFERENCE + BEHAVIORAL_LEARNING memory into context
  (`agent_turn_fleet_wiring.py:1801`, `clue_agents/context.py:419`); the design leg reads PREFERENCE.
  Writers today: Stage-0 interview tools and `draft_account_research_directive@5` (still pinned by
  `head-of-abm@v57`). Deploy master switch `CLUE_MEMORY_ENABLED=false` by default; per-workspace
  toggle row (missing = on). NO human note write route, NO memory list route, no "source thread" field
  on the row (submission carries `trigger` + `creating_quote`).

## Gap map (dummy capability → backend)

| Capability | Backend today | Move |
|---|---|---|
| directory list w/ description, updated, archived, pinned | name/status/created_at only; sidebar read active-only | schema + new read |
| create empty project (name + objective) | Home bootstrap only (needs a message) | new governed tool + route; brand choice |
| edit details | rename only | extend tool (title + description) |
| pin project | none | column + tool |
| archive / restore | column exists, no writer; system project born archived | tool + exclusion of `prj_onb_*` |
| archive chats | per-thread archive | keep loop (as built) |
| recent chats + status | threads list + derived status | exists |
| new chat from home w/ prompt | create thread + submit turn | exists (two calls) |
| instructions | no concept | ruling (project document vs memory vs column) |
| memory notes | substrate exists, off by default, no human write/read routes | ruling |
| accounts on home | not designed in the dummy's home | skip |
| sidebar shared store | own endpoint + invalidation | keep ours, not the dummy's store |

## Rulings requested (see the chat message of 2026-09-19 for the recommendations)
R1 project root route becomes the home; R2 metadata as `project` columns, pin workspace-wide;
R3 empty create: brand picker, born active, zero threads; R4 home composer = real thread + turn
with the full composer; R5 archive: server-side running-work refusal, system projects excluded via a
marker; R6 instructions = `project/instructions.md` project document; R7 memory = surface the real
scoped-memory substrate (list + user_stated write + invalidate), with the fact-shaped rejection shown
honestly and the flag turned on; R8 description feeds the project context card; R9 sidebar order =
pinned first then updated_at; R10 `updated_at` = row updates ⊕ latest thread activity in the read.

## Status
Exploration only. No spec, no plan, no code. Next: founder rulings → design spec under
`docs/superpowers/specs/2026-09-19-projects-page-integration-design.md` → plan → SDD.

## Addendum 2026-09-19 (later) — lane ports, wrapper, spec written

- Founder added `.env` + `apps/frontend/.env.local`; both repointed to the 6-series:
  3026 frontend (`CLUE_APP_ORIGIN`, Clerk authorized parties, `LUMEN_API_CORS_ORIGINS`), 8016 design
  API (`CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, frontend `LUMEN_API_BASE_URL`), 8026 platform
  API (frontend `CLUE_API_BASE_URL`), 8036 platform twin; `DEV_STACK_*` block matches.
  `CLUE_TRIAL_PORT=8010` and `CLUE_PROJECTIONS_PORT=8000` left as found.
- `scripts/dev_stack_fredericton.sh` created from the jerusalem wrapper (untracked; exports the
  `DEV_STACK_*` block from `.env`). Logs `/tmp/fredericton_*`, agent workspaces
  `/private/tmp/clue-agent-workspaces-fredericton`.
- **Still owed before `up`:** database `clue_fredericton`@55040 does not exist (clone live
  `clue_san-salvador` inside the `clue-pg-istanbul` container, then `alembic upgrade head`; head is
  `d659c2d2b537`), `.artifacts/` copy, `lumen-api-helper` build, `CLUE_MEMORY_ENABLED=true` for R7.
- **Spec written (uncommitted, awaiting founder review):**
  `docs/superpowers/specs/2026-09-19-projects-directory-and-home-integration-design.md`, under the
  ten assumed rulings R1–R10 (§1.2) with R3 amended: brand = Home's default-or-first rule, no picker.
- **Founder rule (2026-09-19): 100% visual parity with the dummy, no new visual changes at all.**
  Recorded as spec §1.4: CSS byte-for-byte, components lifted verbatim, no new elements/copy for
  backend concepts, backend text only in the dummy's existing error slots, memory edit made atomic
  server-side (PUT) so the dialog is unchanged; `ProjectComposer` here == the dummy's `ChatComposer`
  (verified diff: identical JSX apart from an unused `home` variant); CSS parity check → F7.

## Addendum 2026-09-19 (later still) — implementation plan written
- `docs/superpowers/plans/2026-09-19-projects-directory-and-home-integration.md` (uncommitted):
  Task 0 lane prerequisites; 1 migration + spine; 2 directory projection; 3 sidebar reorder;
  4 four governed tools + authority entries (registry count 156 → 160); 5 routes; 6 instructions
  (turn-less human writer `create_human_project_document`, kind `project-instructions`);
  7 memory `source_thread_id` + `retire`; 8 memory routes (write seam composed at the HTTP root
  from `build_optional_platform_gateway`, like the display seam); 9 frontend models/repos;
  10 sidebar pin/archive + "Edit project" dialog; 11 lifted screens + byte-equality CSS guard +
  routes + chat-shell link; 12 home composer = thread + first turn; 13 contract doc; 14 (optional
  R8) description on the envelope, card v3; 15 gates + founder-triggered walk + close-out.
- Facts verified while planning: `brand_knowledge_document_kind` CHECK was dropped by
  `639d081ad799` (kind is free text); `write_project_document` requires a `turn_id`, hence the new
  human writer; `ToolContext(workspace_id, actor, conn_factory, operation_id, principal_kind?,
  actor_id?)`; `agent_turn_submission` has FK-heavy NOT NULLs, so the tool test stubs
  `threads_running` instead of seeding a submission; the projections HTTP root already composes
  an optional gateway (Stage-0 recon + display seam), so a memory judge there is precedent, and
  `test_lane_d2_http_gateway_isolation` guards only the turn path/toolbelt.

## Closing entry — implementation landed 2026-09-20 (branch `integration/project-home`, base 21e3ef1e9)
Executed via SDD: Opus implementers, every review and ruling by the controller first-hand. 20 commits
`5e963f62a..eb0484e7d`. Landed: migration `5358a2422cb2` (project description/pinned/kind/updated_at/
archived_at + memory.source_thread_id); spine writers; directory projection (`clue_projections.projects`)
and the sidebar re-ordered pinned-first by composite activity (active threads only); four ungranted
human-only tools `create_project@1` / `update_project_details@1` / `set_project_pinned@1` /
`set_project_archived@1` (registry 156 → 160); routes `GET /api/v1/projects`, `POST /projects/blank`,
`PATCH /projects/{id}` (title/description/pinned; label edits go through update_project_details@1),
`POST /projects/{id}/archive`; `create_thread@1` refuses archived projects; instructions as the project
document `project/instructions.md` (`GET/PUT /frontend/v1/projects/{id}/instructions`, turn-less human
writer `create_human_project_document`, excluded from the documents LIST); memory notes over the scoped-
memory seam (`GET/POST/PUT/DELETE /frontend/v1/projects/{id}/memory[/{id}]`, `retire` verb,
`source_thread_id`, write seam composed at the HTTP root from the optional gateway); frontend models/
repositories, sidebar pin + archive + "Edit project" dialog, nav label "Projects", the six lifted
components (CSS byte-identical, pinned by sha256; `projects-screen.tsx` drops its embedded shell per
R7), invalidation provider hoisted to `(protected)/layout.tsx`, home composer = real thread + first turn,
contract doc section. Task 14 (description on the envelope) SKIPPED pending R8.
Gates: backend named suites green except the pre-existing composer-context red; ruff clean except 4
pre-existing errors in design_leg_wiring.py; mypy/lint-imports clean; db-smoke clean; one head.
Frontend 3204/3205 (1 pre-existing skip), lint 0 errors, build green. `tests/arv2/test_import_guard.py`
fails on two pre-existing offenders (not this branch's).
Lane: DB `clue_fredericton`@55040 (istanbul container, role `clue`), throwaway `clue_fredericton_smoke`
for `make db-smoke` (it reads CLUE_DATABASE_URL and downgrades to base — never point it at the lane DB);
`.artifacts` copied; helper built; CLUE_MEMORY_ENABLED=true.
OWED (founder-triggered): the ten-step browser walk (plan Task 15 step 4) on 3026/8016/8026/8036;
rulings R1–R10 remain assumed; F1–F7 from the spec stand.

## 2026-09-20 — founder ruling: no "← project" link in the chat shell
The dummy's `chatProjectLink` element above the conversation stage (lifted in Task 11) is removed
from `chat-surface.tsx` on the founder's request after the first live look; the sidebar's project
row is the way back to the project home. Spec §2.5 "Chat shell" paragraph is superseded.

## 2026-09-20 — founder ruling: ship with CLUE_MEMORY_ENABLED=true
Live proof on the lane: the human note written 11:20:56 (judge verdict add, born active) was
included in the next turn's assembled bundle at 11:21:28 (`memory_bundle_journal`, recipe
recipe0-stage0@28). `.env.example` default flipped false → true with the R0 posture comment
rewritten; spec follow-up F5 is closed. Owner action per environment that predates R0: count
`memory` rows by scope/provenance before enabling.
