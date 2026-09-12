# Project Plan Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM writes the project's `plan.md` once the strategy, ICP and product set are settled; the user reads and edits it in a Plan tab beside Gallery and Target accounts; a "proposed a plan" card in the chat opens the tab; the same document surface renders project-scoped ICP and persona documents opened from the gallery.

**Architecture:** A root-level write tool stores `project/plan.md` as a `project-plan` knowledge document with `project_id` set (plan 2's schema), refusing when the version it read is no longer current. A project-documents read/write router under `frontend_read` mirrors the Knowledge editor's PUT contract. The frontend gains a `"plan"` rail surface, a `ProjectDocumentSurface` (breadcrumb header, Preview / Edit, Save / Discard, markdown article) built from lifted Knowledge-editor pieces, a pure `planWriteToOpen` signal, and a click-through from the plan card. Skill v24 / profile v47 / recipe v25 grant the tool.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy async), the `clue_toolbelt` `Tool` envelope; Next.js App Router + TypeScript, Zod, CSS modules with `@clue/design-system` tokens, `react-markdown` + `remark-gfm`, CodeMirror; `node --test` via `tsx` for `.test.ts` only (no DOM).

**Spec:** `docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.3 (rulings R3, R6, R7). Depends on plans 1 and 2.

## Global Constraints

- Presentation truth is the dummy's Plan tab (ruling R6): tab label "Plan" with the `file-text` icon beside Gallery and Target accounts; a slim header with the file icon and the document's name; a centred markdown article. Every style uses `--clue-ds-*` tokens; no raw hex, no raw `"Satoshi"` font stacks (use `--clue-ds-typography-*`); `src/design-system-tokens.test.ts` must stay green.
- Frontend architecture: presentation components never import repositories, fixtures, env or transport; every payload has a Zod schema in `model/` and a repository in `data/`; the check gate is `npm run design-system:build && npm run lint && npm run build`, plus `npm test`.
- Tests are `.test.ts` only, `node:test` + `node:assert/strict`, no DOM: pure rules live in `model/` and are unit-tested; component wiring is pinned by source-regex contract tests (`chat-shell-contract.test.ts` style). Touching the auto-open effects in `chat-surface.tsx` means updating that test.
- The write path is one immutable version per save with `expectedRevision`; a `confirmed`-style approval stamp does not exist for plans, but `user_edit` provenance is recorded exactly as the Knowledge PUT does.
- Skill/profile/recipe immutability and the two-commit grant recipe as in plan 2.
- No `git push`, no PRs, no AI attribution; offline suites without `.env`; DB suites on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`.

---

## File structure

**Backend**

| File | Responsibility |
|---|---|
| `platform/api/clue_api/arv2/project_documents.py` | `write_project_plan(conn, storage, request)` (deterministic id, revision check, front matter), `list_project_documents`, `read_project_document`, `save_project_document` (the human PUT). |
| `platform/api/clue_api/project_document_tools.py` | `WriteProjectDocumentTool` (`write_project_document@1`), `build_project_document_tools`. |
| `platform/api/clue_api/frontend_read/project_documents.py` | `GET /projects/{project_id}/documents`, `GET …/documents/{document_id}`, `PUT …/documents/{document_id}`. |
| `platform/api/clue_api/conversation_turns.py` | `_PLAN_OBJECT_TYPES` gains `project_document`; the plan part title for it is "Plan". |
| Registration + grant | `toolbelt_wiring.py`, `agent_registry_wiring.py`, `fleet_main.py`, `projections_main.py`, `frontend_read/app.py`; skill v24, profile v47, recipe v25 and the pinned tests. |

**Frontend (`apps/frontend/src`)**

| File | Responsibility |
|---|---|
| `features/projects/model/project-documents.ts` | Zod schemas: `ProjectDocumentSummarySchema`, `ProjectDocumentDetailSchema`, `ProjectDocumentsResponseSchema`; `ProjectDocument` types; `planDocumentOf(list)`. |
| `features/projects/data/project-documents.repository.ts` | Server-side reads via `fetchRead`; `saveProjectDocument(document, body)` client PUT with the 409/401/403 messages. |
| `app/api/projects/[projectId]/documents/route.ts`, `app/api/projects/[projectId]/documents/[documentId]/route.ts` | BFF: list; detail + PUT. |
| `features/chat-shell/model/chat-shell.ts`, `hooks/use-editor-shell-controller.ts`, `model/chat-surface-params.ts` | Surface `"plan"`: type unions, `open-plan` action, `openPlan`, URL `?surface=plan`. |
| `features/chat-shell/model/plan-write-signal.ts` (+ test) | `PLAN_WRITE_TOOL = "write_project_document"`, `planWriteToOpen(...)`. |
| `features/chat-shell/components/artifact-tabs.tsx`, `artifact-stage.tsx`, `chat-surface.tsx` | The Plan tab, the pane, the auto-open effect, `onOpenPlan` into chat parts. |
| `features/projects/components/chat-message-part.tsx` | The plan card calls `actions.onOpenPlan()` when `part.planRef.objectType === "project_document"`. |
| `components/markdown/markdown-article.tsx`, `markdown-source-editor.tsx`, `markdown.module.css`, `hooks/use-markdown-source-editor.ts` | Lifted from brand-context: the preview article and the CodeMirror editor, shared. |
| `features/projects/hooks/use-project-document-editor.ts` | The draft/base/in-flight/rebase state machine with an injected save. |
| `features/projects/hooks/use-project-documents.ts` | Loads the project's documents; `refreshToken` refetch; exposes `plan`. |
| `features/projects/components/project-document-surface.tsx` + `project-document-surface.module.css` | Header (file icon + name, Preview/Edit, Save/Discard/Saved), article or editor. |
| `features/projects/model/chat-tool-presentation.ts` | Label `write_project_document: "Write the project plan"`. |
| `features/gallery/model/project-gallery.ts`, `components/gallery-artifact-card.tsx`, `features/chat-shell/model/gallery-card-target.ts` | Document cards (project ICP/persona) in the gallery; opening one lands on the document surface with that document. |

Delete: `features/projects/components/project-plan.tsx` and `ProjectPlanSchema`/`ProjectPlan` in `model/project-workspace.ts` (orphaned dummy lift, replaced by this plan).

---

### Task 1: `write_project_plan` and the project-documents read/write functions

**Files:**
- Create: `platform/api/clue_api/arv2/project_documents.py`
- Test: `tests/arv2/test_project_documents_db.py`

**Interfaces:**

```python
PLAN_PATH = "project/plan.md"
PLAN_KIND = "project-plan"

@dataclass(frozen=True, slots=True)
class ProjectPlanWrite:
    workspace_id: str; brand_id: str; project_id: str; turn_id: UUID; user_id: str
    body: str; expected_version: int | None

@dataclass(frozen=True, slots=True)
class WrittenDocument:
    document_id: UUID; path: str; version: int; workspace_path: str; replayed: bool

class ProjectDocumentRefused(Exception):  # .code, message
#   codes: project_document_revision_conflict, project_document_body_empty, project_document_version_race

def plan_document_id(*, turn_id: UUID, expected_version: int | None) -> UUID
#   uuid5(NAMESPACE_URL, f"arv2-project-plan:{turn_id}:{expected_version or 0}")

async def write_project_plan(conn, storage, request: ProjectPlanWrite, *, now=_utcnow) -> WrittenDocument
async def current_plan_version(conn, *, workspace_id, project_id) -> int | None

@dataclass(frozen=True, slots=True)
class ProjectDocumentRow:
    document_id: UUID; path: str; kind: str; version: int; status: str; updated_at: datetime
    artifact_key: str; artifact_sha256: str; icp_key: str | None

async def list_project_documents(conn, *, workspace_id, project_id) -> tuple[ProjectDocumentRow, ...]
#   DISTINCT ON (path) … WHERE workspace_id AND project_id = :p AND status = ANY(servable) ORDER BY path, version DESC
async def read_project_document(conn, storage, *, workspace_id, project_id, document_id) -> tuple[ProjectDocumentRow, dict[str, Any], str] | None   # row, front matter, body
async def save_project_document(conn, storage, *, workspace_id, project_id, document_id, body: str, expected_revision: int, user_id: str) -> ProjectDocumentRow
#   the human PUT: same rules as frontend_read.brand_knowledge.save_knowledge_document, scoped by project_id; a confirmed ICP edit becomes `proposed` and drops the approval stamp
```

`write_project_plan`:
1. `body.strip()` empty → `project_document_body_empty`.
2. Replay: a row with `plan_document_id(...)` exists → `WrittenDocument(replayed=True)`.
3. `current = await current_plan_version(...)`; if `current != request.expected_version` → `project_document_revision_conflict` with message `f"plan.md is at version {current}; you expected {expected_version}. Re-read inputs/project/plan.md and write again."` (`None` vs `None` is equal: first write).
4. Front matter: `{"kind": PLAN_KIND, "project_id": …, "brand_id": …, "status": "ready", "authored_by": {"turn_id": …, "user_id": …}, "authored_at": now().isoformat()}`; `render_markdown(KnowledgeDocument(kind=PLAN_KIND, folder="project", path=PLAN_PATH, front_matter=front, body=body, cost=None))`; `content_address`, `artifact_key`, `record_artifact(source_key="arv2-project-plan")`, `storage.put`.
5. INSERT `(document_id, workspace_id, brand_id, project_id, folder='project', path, kind, version=(current or 0)+1, status='ready', artifact_key, artifact_sha256, supersedes_document_id=<current servable row id or NULL>) ON CONFLICT (document_id) DO NOTHING`; `IntegrityError` on `brand_knowledge_document_scope_path_version` → `project_document_version_race`.
6. `UPDATE … SET status='superseded' WHERE workspace_id AND project_id AND path AND document_id <> :id AND status IN ('ready','proposed')`.
7. Return `WrittenDocument(workspace_path="inputs/project/plan.md")`.

- [ ] **Step 1: Failing tests** — first write (version 1, `expected_version=None`); a second write with `expected_version=1` → version 2 supersedes 1; a write with a stale `expected_version` → `project_document_revision_conflict`; replay returns the same id; `list_project_documents` lists only the current version; `read_project_document` returns front matter with `kind == "project-plan"` and the body verbatim; `save_project_document` from the human mints version 3 with `front["user_edit"]` and a stale `expected_revision` refuses; a foreign `project_id` reads as absent.
- [ ] **Step 2: Run (fail). Step 3: implement. Step 4: run `tests/arv2/test_project_documents_db.py tests/arv2/test_import_guard.py`, ruff, mypy.**
- [ ] **Step 5: Commit** — `git commit -m "feat(arv2): project/plan.md — write with revision check, list/read/save for the project's documents"`.

---

### Task 2: The tool `write_project_document@1` (registered ungranted) and the plan part

**Files:**
- Create: `platform/api/clue_api/project_document_tools.py`
- Modify: `toolbelt_wiring.py` (kwarg `project_documents: ProjectDocumentService | None = None`; register), `agent_registry_wiring.py` (`"write_project_document": ()`), `fleet_main.py`/`projections_main.py` (compose `DbProjectDocumentService(storage)` when storage exists), `conversation_turns.py:132` (`_PLAN_OBJECT_TYPES` adds `"project_document"`; the `emit_plan_part` call uses `title="Plan" if ref.object_type == "project_document" else ref.object_type.replace("_", " ")` and `revision_label=f"v{ref.version}"` for it)
- Test: `tests/api/test_project_document_tool.py` (offline), the count bumps (`test_toolbelt_wiring.py`, `test_tool_authority_audit.py`, `test_agent_registry_wiring.py`), `tests/api/test_conversation_turns*.py` (a `project_document` domain ref projects a plan part titled "Plan")

**Interfaces:**

```python
class WriteProjectDocumentInput(ToolInput):
    document: Literal["plan"]
    body: str = Field(min_length=1, max_length=200_000)
    expected_version: int | None = Field(default=None, ge=1)
    source_turn_ref: Annotated[str, ...] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})

class WriteProjectDocumentOutput(ToolOutput):
    document_id: str; path: str; version: int; workspace_path: str; replayed: bool

class WriteProjectDocumentTool(Tool):
    name = "write_project_document"; version = "1"; effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(policy=ReplayPolicy.DOMAIN_IDEMPOTENT, durable_identity="presenting turn + document + expected version", external_boundary=ExternalReplayBoundary.NONE)
    parameter_policy = JournalParameterPolicy(safe_display_fields=("document", "expected_version"))
    pin_requirements = ("project",)
```

`model_description`: "Write this project's plan (inputs/project/plan.md) as markdown: the execution plan you and the human settled — outcome, the confirmed profile and products, the account motion, channels, owners, what day ninety looks like, and the next steps. Write it once the strategy, the ICP and the product set are agreed, never on the first turn. Pass expected_version = the version of the file you read (omit it only when no plan exists yet); the platform refuses when the human has edited it since, and you then re-read it. The new version appears in your workspace on the next turn. Include {object_type: 'project_document', object_id: <document_id>, version: <version>} in your finalization's domain_refs so the plan card appears in the chat."

The `_resolve` is the same turn binding as plan 2's authoring tool (turn ref → turn → project in workspace → brand id, user id).

- [ ] **Step 1–4: tests, implement, register, run** (`tests/api/test_project_document_tool.py tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_conversation_turns*.py`).
- [ ] **Step 5: Commit** — `git commit -m "feat(head-of-abm): write_project_document@1 — the project plan written with a revision check, registered ungranted; project_document refs project as the plan card"`.

---

### Task 3: The project-documents HTTP surface

**Files:**
- Create: `platform/api/clue_api/frontend_read/project_documents.py`
- Modify: `platform/api/clue_api/frontend_read/app.py` (register after `register_research_progress_route`)
- Test: `tests/api/test_frontend_read_project_documents_db.py`

**Interfaces (wire, snake_case, `{data: …}` like the sibling routes):**

```
GET  /frontend/v1/projects/{project_id}/documents
  → {data: {documents: [{id, path, kind, title, version, status, updated_at, icp_key}]}}
GET  /frontend/v1/projects/{project_id}/documents/{document_id}
  → {data: {id, path, kind, title, version, status, updated_at, icp_key, markdown, front_matter}}
PUT  /frontend/v1/projects/{project_id}/documents/{document_id}   body {body, expected_revision}
  → the detail shape; 409 {code: DOCUMENT_REVISION_CONFLICT}; 401/403 as the Knowledge PUT; 503 KNOWLEDGE_STORAGE_UNAVAILABLE
```

`title`: for `project-plan` → "Plan"; for `icp-definition` → the front matter `title` or the H1 (reuse `icp_confirmation._title`); for `audience-persona` → "Personas — <icp_key>". `register_project_document_routes(router, *, conn_factory, storage, allow_local_mutations)`; permission `project.write` on PUT via `principal_from_request`, exactly as `brand_knowledge.put_knowledge_document`.

- [ ] **Step 1: Failing route tests** (the `TestClient` pattern of `tests/api/test_frontend_read_discovery_status_db.py` or the brand-knowledge route tests): list, detail, PUT success (new version, `user_edit`), PUT 409 on stale revision, 404 for another project's document.
- [ ] **Step 2–4: implement, register, run;** ruff, mypy.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend-read): the project's documents — list, detail, and the versioned PUT the Plan tab edits through"`.

---

### Task 4: Frontend model, repository, BFF

**Files:**
- Create: `apps/frontend/src/features/projects/model/project-documents.ts` (+ `.test.ts`), `apps/frontend/src/features/projects/data/project-documents.repository.ts`, `apps/frontend/src/app/api/projects/[projectId]/documents/route.ts`, `apps/frontend/src/app/api/projects/[projectId]/documents/[documentId]/route.ts`
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
export interface ProjectDocumentDetail extends ProjectDocument { markdown: string }
export function toProjectDocument(wire): ProjectDocument
export function planDocumentOf(documents: readonly ProjectDocument[]): ProjectDocument | null   // path === "project/plan.md"
export function documentEditedLabel(updatedAt: string, now: Date): string   // "Edited just now" | "Edited 5 min ago" | "Edited today at 14:02" | "Edited 12 Sep" — pure, tested
```

```ts
// data/project-documents.repository.ts
export async function listProjectDocuments(projectId, read = fetchRead): Promise<ProjectDocument[]>
export async function getProjectDocument(projectId, documentId, read = fetchRead): Promise<ProjectDocumentDetail>
export async function saveProjectDocument(projectId, document: ProjectDocument, body: string, clueFetch = fetch): Promise<ProjectDocumentDetail>
//   PUT /api/projects/{projectId}/documents/{id} with { body, expectedRevision: document.version }
//   409 → "A newer version of the plan exists. Your changes are still here; copy them before loading the latest version."
//   401/403 → "You do not have permission to edit this document."
```

BFF routes copy `app/api/projects/[projectId]/discovery/route.ts`: `GET` list; `GET` detail; `PUT` forwards `{ body, expected_revision: expectedRevision }` through the authenticated backend client used by the accounts bulk-action route (find the mutation helper that route uses; it already enforces origin and workspace stamping), returns the backend status and body verbatim on 409/401/403.

- [ ] **Step 1: Failing model tests** — schema parse of a list payload; `planDocumentOf`; `documentEditedLabel` for the four cases.
- [ ] **Step 2–4: implement; run `npm test`, `npm run lint`.**
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): project documents model, repository and BFF routes; drop the orphaned dummy plan lift"`.

---

### Task 5: Shared markdown pieces lifted from Brand Context

**Files:**
- Create: `apps/frontend/src/components/markdown/markdown-article.tsx`, `components/markdown/markdown-source-editor.tsx`, `components/markdown/markdown.module.css`, `components/markdown/use-markdown-source-editor.ts`
- Modify: `features/brand-context/components/knowledge-panel.tsx` and `brand-context-header.tsx` to import the shared pieces; delete `features/brand-context/components/markdown-source-editor.tsx` and `hooks/use-markdown-source-editor.ts`; move the `.markdownPreview` and `.markdownEditor` blocks out of `brand-context.module.css` into `markdown.module.css`

**Interfaces:**

```tsx
export function MarkdownArticle({ markdown, className }: { markdown: string; className?: string })   // <article className={styles.markdownArticle}><Markdown remarkPlugins={[remarkGfm]}>…</Markdown></article>
export default function MarkdownSourceEditor({ value, onChange, readOnly }: {...})   // default export for next/dynamic
export function useMarkdownSourceEditor(value, onChange, readOnly): RefObject<HTMLDivElement>
```

`markdown.module.css` = the `.markdownPreview` rules (renamed `.markdownArticle`) and `.markdownEditor` rules, with every `font: … "Satoshi", Arial, sans-serif` shorthand replaced by the typography tokens: h1 → `--clue-ds-typography-tittle-default-*`, h2 → `--clue-ds-typography-text-lg-medium-*`, h3–h6 → `--clue-ds-typography-text-default-medium-*`, p/li/table → `--clue-ds-typography-text-default-*`, code/pre → `--clue-ds-typography-code-*`. Colours and borders keep their existing semantic tokens. Verify each token name exists in `packages/design-system/generated/tokens.css` before use (the token test fails otherwise).

- [ ] **Step 1: Move the files; update the two brand-context imports; run the 92 brand-context tests, `npm run lint`, `npm run build`, `npm test` (token test).**
- [ ] **Step 2: Browser check** on this lane's frontend (:3020): the Knowledge page still renders and edits a document (Preview → Edit → type → Preview → Discard).
- [ ] **Step 3: Commit** — `git commit -m "refactor(frontend): shared markdown article + source editor under components/markdown, typography on design tokens"`.

---

### Task 6: The Plan surface — shell state, tab, pane, editor hook

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
): { body; canEdit; dirty; discard; editorOpened; mode: "preview" | "edit"; error; save; setBody; saving; busy; saved; setMode }

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

- [ ] **Step 1: Failing tests** — `chat-surface-params.test.ts`: `?surface=plan` hydrates `surface: "plan"`, `panelOpen: true`; pane params serialize back to `surface: "plan"` with no artifact vocabulary. A new `features/projects/hooks/use-project-document-editor.test.ts` is not possible (hooks need React); instead test the pure reducer pieces if you extract them (`draftAfterChange(drafts, path, base, body)` returns the drafts map with the entry removed when `body === base.body`) — put that pure function in `model/project-document-draft.ts` with a test.
- [ ] **Step 2–3: implement.** Run `npm test`, `npm run lint`, `npm run build`.
- [ ] **Step 4: Browser check** (:3020): open a project chat, `?surface=plan` shows the empty state; the tab is keyboard-reachable (Arrow keys move between Gallery / Target accounts / Plan).
- [ ] **Step 5: Commit** — `git commit -m "feat(chat-shell): the Plan surface — tab, pane, URL state, and the project document editor on shared markdown pieces"`.

---

### Task 7: Auto-open on write, the plan card click, labels

**Files:**
- Create: `features/chat-shell/model/plan-write-signal.ts` + `plan-write-signal.test.ts`
- Modify: `features/chat-shell/components/chat-surface.tsx` (the effect; `planPrime` state; `onOpenPlan` in the part actions), `features/projects/components/chat-message-part.tsx` (`ChatPartActions.onOpenPlan?: () => void`; the `case "plan"` arm wraps the header in a button when `part.planRef.objectType === "project_document"` and `actions.onOpenPlan` exists: `<PlanTitle>` becomes `<button type="button" className={styles.planOpenButton} onClick={actions.onOpenPlan}>{part.title}</button>`), `features/projects/components/project-flow.module.css` (`.planOpenButton`: inherit typography, `color: var(--clue-ds-color-content-neutral)`, underline on hover, no background/border), `features/projects/model/chat-tool-presentation.ts` (+ test) (`write_project_document: "Write the project plan"`), `features/chat-shell/model/chat-shell-contract.test.ts` (pin the new effect)

**Interfaces:**

```ts
export const PLAN_WRITE_TOOL = "write_project_document";
export function planWriteToOpen({ transcript, knownToolCallIds }): string | null   // identical rule to discoveryLaunchToOpen, keyed on PLAN_WRITE_TOOL
```

The effect in `chat-surface.tsx` copies the discovery effect (lines 341–370) with its own `knownPlanWriteIds` ref, calling `shell.openPlan()` and `setPlanPrime(c => c + 1)`; both invariants hold (wait on `chat.loading`; bank only `output-available`). Where `ChatPartActions` is built (in `use-project-chat-controller.ts` or `chat-surface.tsx` — find the object literal that supplies `gateFor`), add `onOpenPlan: shell.openPlan`.

- [ ] **Step 1: Failing tests** — `plan-write-signal.test.ts` (copy `discovery-launch-signal.test.ts`'s cases against the new tool name); the contract test asserts `/planWriteToOpen\(\{[\s\S]*?openPlan\(\);\s*setPlanPrime\(/` in `chat-surface.tsx` and that `chat-message-part.tsx` matches `/planRef\.objectType === "project_document"/`; the label test.
- [ ] **Step 2–3: implement; run `npm test`, lint, build.**
- [ ] **Step 4: Commit** — `git commit -m "feat(chat-shell): the Plan tab opens itself when the agent writes the plan, and the plan card opens it on click"`.

---

### Task 8: Project documents in the gallery

**Files:**
- Modify: `features/gallery/model/project-gallery.ts` (`GalleryArtifact` gains `documentKind?: "icp-definition" | "audience-persona" | "project-plan"` and `documentId?: string`), `features/gallery/components/gallery-artifact-card.tsx` (a document card: `file-text` icon in the preview frame, no image; title; `editedLabel`), `features/chat-shell/model/gallery-card-target.ts` (+ test) (`documentKind` present → `{ surface: "plan", documentId }`), `features/chat-shell/components/chat-surface.tsx` (`onOpenGalleryArtifact`: `if (target.surface === "plan") { setOpenDocumentId(target.documentId); shell.openPlan(); return; }`), the gallery feed composition (`app/(protected)/projects/[projectId]/chats/[chatId]/page.tsx`): merge `listProjectDocuments(projectId)` (ICP and persona kinds only; the plan has its own tab) into the feed's cards as document cards, mapped by `toDocumentCard(document): ProjectArtifact`-shaped `GalleryArtifact`
- Test: `gallery-card-target.test.ts` (document → plan surface), `project-gallery.test.ts` (document cards sort by `updatedAt` with the rest; the type filter "Documents" appears only when a document card exists)

- [ ] **Step 1: Failing tests. Step 2–3: implement; `npm test`, lint, build.**
- [ ] **Step 4: Browser check**: with a project-local ICP present (plan 2's walk), the gallery shows a document card; clicking it opens the Plan surface on that document, with the header naming it ("GI-focused ASCs"), Preview/Edit working, and Save minting a new version (verify with `SELECT version, status FROM brand_knowledge_document WHERE project_id = :p AND path = 'audience/icp-gi-dac.md' ORDER BY version`).
- [ ] **Step 5: Commit** — `git commit -m "feat(gallery): project ICP and persona documents appear as document cards and open on the document surface"`.

---

### Task 9: The grant — skill v24, profile v47, recipe v25

**Files:** as plan 2 Task 6, one version further: `skills/stage0-interview/v24`, `profiles/head-of-abm/v47`, `recipe0-stage0-v25.json`, `CONVERSATION_RECIPE_VERSION = 25`, `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v47"`, authority row `(AgentRole.HEAD_OF_ABM,)`, trial surface withheld set, `stage0_recipe.py` `_presenting_turn_project_pin` branch, all pinned tests and the new manifest digest.

**Skill v24 — new §6b after §6 (everything else v23 verbatim; `summary` appends ", and write the project plan once the strategy is settled"):**

```
## 6b. Write the plan

A project has one plan, `inputs/project/plan.md`, and you write it. Write it once — not before — the section 2 questions are answered, the ICP is confirmed and pinned (the index card names it) and the product set is confirmed. Never write a plan on the first turn of a project, and never write one the human has not discussed with you.

The plan is the execution plan in the human's terms, as markdown: a title; the outcome; the confirmed profile and the products, by name; the account motion (how many accounts, discovered or imported, what tier gets deep research); the channels and sequence; who owns follow-up; what day ninety looks like; the next three steps. Keep it under two screens. Facts about the company or products come from the files; decisions come from `decisions.md` and the conversation.

Call `write_project_document` with `document: "plan"`, the markdown `body`, and `expected_version` equal to the version of `inputs/project/plan.md` you read this turn (omit it when the file does not exist). When the platform refuses because the human edited the plan since, re-read the file, keep their edits, and write again. Include `{object_type: "project_document", object_id: <document_id>, version: <version>}` in `domain_refs` when you finalize, so the plan card appears in the chat and the Plan tab opens.

When the human changes course later — a new profile, a different channel, a different list size — update the plan the same way and say what changed. Read `inputs/project/plan.md` before proposing anything that departs from it.
```

- [ ] **Step 1–3: mint, flip, digest, run the R4 gate command twice + `tests/execution/test_recipes.py`, commit** — `git commit -m "feat(head-of-abm): v47 grants write_project_document@1 — skill v24 §6b says when and how the plan is written; recipe v25 admits it"`.

---

### Task 10: Live proof and close-out

- [ ] **Step 1:** Restart this lane's API twins, workers and frontend (`./scripts/dev_stack_san_salvador.sh restart-api > /tmp/san-salvador_restart.log 2>&1; … restart-workers …; … restart-frontend …` — use the wrapper's actual subcommands from `scripts/dev_stack_san_salvador.sh`; never pipe).
- [ ] **Step 2:** On the project from plan 2's walk (ICP confirmed, products confirmed): ask the agent for the plan → `write_project_document` in the transcript → the Plan tab opens by itself → the plan card in the chat → click the card from a fresh page load opens the tab → Edit, change a line, Save → `SELECT version, status FROM brand_knowledge_document WHERE project_id = :p AND path = 'project/plan.md' ORDER BY version` shows v1 superseded, v2 ready with `user_edit` → in a **new thread**, ask the agent to add a step → it re-reads, writes v3 keeping your edit → `status.md`'s Plan line shows version 3.
- [ ] **Step 3:** `_memory/2026-09-12-project-plan-document.md` close-out, README row, `apps/frontend/docs/api-contracts/projects.md` gains the documents contract (the three routes and the `?surface=plan` deep link), `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum line.
- [ ] **Step 4: Commit** — `git commit -m "docs(project-plan): close-out — contract, memory, live proof"`.

---

## Self-review

- Spec §4.3 coverage: tool + revision refusal (T1–T2), plan part (T2), HTTP surface (T3), model/repository/BFF (T4), shared markdown on tokens (T5), surface + tab + pane + editor (T6), auto-open + card click + label (T7), documents in the gallery (T8), grant (T9). ✔
- Placeholder scan: the one "find the mutation helper that route uses" names the file to look in (`bulk-action` route); acceptable as a locate step, not a design gap. ✔
- Type consistency: `ProjectPlanWrite.expected_version: int | None` ↔ tool input `expected_version: int | None` ↔ HTTP `expected_revision` (human) — the human path deliberately uses the Knowledge name; `planDocumentOf` returns `ProjectDocument | null` in T4 and T6; `openPlan` on the controller in T6 and used in T7/T8; `planRefreshToken` ↔ `planPrime` naming stated in T6/T7. ✔
