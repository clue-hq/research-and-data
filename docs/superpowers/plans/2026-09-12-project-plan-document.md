# Project Plan Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM writes the project's `plan.md` once the strategy, ICP and product set are settled, on a versioned path the user can also edit through a project-documents PUT. (The Plan tab and editor are the deferred frontend plan.)

**Architecture:** A root-level write tool stores `project/plan.md` as a `project-plan` knowledge document with `project_id` set (plan 2's schema), refusing when the version it read is no longer current. A project-documents read/write router under `frontend_read` mirrors the Knowledge editor's PUT contract, so the deferred Plan tab plugs in at the repository seam later. Skill v24 / profile v47 / recipe v25 grant the tool.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy async), the `clue_toolbelt` `Tool` envelope, pytest on the lane DB. (Frontend: deferred plan.)

**Spec:** `docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.3 (rulings R3, R7, R12). Depends on plans 1 and 2. The frontend half is `2026-09-12-plan-tab-frontend.md` (deferred).

## Global Constraints

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

**Frontend:** deferred — see `docs/superpowers/plans/2026-09-12-plan-tab-frontend.md`. The one frontend line in this plan is the tool label in `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` (Task 9).

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

### Tasks 4–8: DEFERRED — the frontend surface

Founder ruling 2026-09-12 (R12): this pass ships the backend and the agent capabilities only. The
Plan tab, the document editor, the plan-card click, auto-open and the gallery document cards are
`docs/superpowers/plans/2026-09-12-plan-tab-frontend.md` (deferred, executed later together with the
markdown toolbar slice). Task 7's tool label (`write_project_document: "Write the project plan"`) is
the one frontend line kept in this plan: it lands in Task 9 so the transcript names the tool.

---

### Task 9: The grant — skill v24, profile v47, recipe v25

**Files:** as plan 2 Task 6, one version further: `skills/stage0-interview/v24`, `profiles/head-of-abm/v47`, `recipe0-stage0-v25.json`, `CONVERSATION_RECIPE_VERSION = 25`, `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v47"`, authority row `(AgentRole.HEAD_OF_ABM,)`, trial surface withheld set, `stage0_recipe.py` `_presenting_turn_project_pin` branch, all pinned tests and the new manifest digest.

Also in this task: `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` gains `write_project_document: "Write the project plan"` (+ its test line); run `cd apps/frontend && npm test && npm run lint`.

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

- [ ] **Step 1:** Restart this lane's API twins and workers (`./scripts/dev_stack_san_salvador.sh restart-api > /tmp/san-salvador_restart.log 2>&1; … restart-workers …; … restart-frontend …` — use the wrapper's actual subcommands from `scripts/dev_stack_san_salvador.sh`; never pipe).
- [ ] **Step 2:** On the project from plan 2's walk (ICP confirmed, products confirmed): ask the agent for the plan → `write_project_document` in the transcript and the plan card in the chat (the `plan` part; its click-through is deferred) → `SELECT version, status FROM brand_knowledge_document WHERE project_id = :p AND path = 'project/plan.md' ORDER BY version` shows v1 ready → `PUT /frontend/v1/projects/{id}/documents/{document_id}` with `{body, expected_revision: 1}` through `curl` on this lane's API (an edited line) → v1 superseded, v2 ready with `user_edit` → in a **new thread**, ask the agent to add a step → it re-reads `inputs/project/plan.md`, writes v3 keeping the edit → `status.md`'s Plan line shows version 3.
- [ ] **Step 3:** `_memory/2026-09-12-project-plan-document.md` close-out, README row, `apps/frontend/docs/api-contracts/projects.md` gains the documents contract (the three routes and the `?surface=plan` deep link), `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum line.
- [ ] **Step 4: Commit** — `git commit -m "docs(project-plan): close-out — contract, memory, live proof"`.

---

## Self-review

- Spec §4.3 coverage: tool + revision refusal (T1–T2), plan part (T2), HTTP surface (T3), model/repository/BFF (T4), shared markdown on tokens (T5), surface + tab + pane + editor (T6), auto-open + card click + label (T7), documents in the gallery (T8), grant (T9). ✔
- Placeholder scan: the one "find the mutation helper that route uses" names the file to look in (`bulk-action` route); acceptable as a locate step, not a design gap. ✔
- Type consistency: `ProjectPlanWrite.expected_version: int | None` ↔ tool input `expected_version: int | None` ↔ HTTP `expected_revision` (human) — the human path deliberately uses the Knowledge name; `planDocumentOf` returns `ProjectDocument | null` in T4 and T6; `openPlan` on the controller in T6 and used in T7/T8; `planRefreshToken` ↔ `planPrime` naming stated in T6/T7. ✔
