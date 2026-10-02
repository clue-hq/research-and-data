# 2026-09-12 — the project plan document (plan 3 of the context + ICP-authoring set)

Branch `research-streaming`, worktree `san-salvador`, lane DB `clue_san-salvador`. Plan
`docs/superpowers/plans/2026-09-12-project-plan-document.md`; spec
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.3 (rulings R3,
R7, R12). SDD ledger and per-task reports: `.superpowers/sdd/2026-09-12-project-plan-document/`
(git-ignored). Base `71b8618ff` (plan 2's close-out). Commits `7256ee0d2`, `1a2c8264b`,
`345bd0fe1`, `93af298c3`, and this close-out.

## The problem it solves

Plan 1 gave a project `inputs/project/status.md` and `decisions.md`; plan 2 let the Head of ABM
author the profile it sells to. Neither produced the thing a marketer actually asks for — **the
plan**: what we are doing for this project, for which profile and products, over which channels,
in what order. It now exists as one versioned document, `project/plan.md`, that the agent writes
and the human can edit, each save an immutable new version guarded by the version the writer read.

**Backend and grant only.** Founder ruling **R12** defers the Plan tab, the editor, the plan-card
click-through, the auto-open and the gallery document cards to
`docs/superpowers/plans/2026-09-12-plan-tab-frontend.md` (tasks 4–8, to run later with the
markdown-toolbar slice `docs/superpowers/specs/2026-09-12-markdown-editor-toolbar-design.md`).

## What shipped, per task

**T1 — `7256ee0d2` — the store.** `platform/api/clue_api/arv2/project_documents.py` (new).
`PLAN_PATH = "project/plan.md"`, `PLAN_KIND = "project-plan"`, `PLAN_FOLDER = "project"`,
`PLAN_WORKSPACE_PATH = "inputs/project/plan.md"` (a restated constant mirroring plan 1's ruling F
rule `project_context_files.project_workspace_path`, which the import guard forbids importing
here), `PLAN_SOURCE_KEY`, `USER_EDIT_SOURCE_KEY`.
`write_project_plan(conn, storage, request)` — body empty → `project_document_body_empty`; replay
short-circuits on the derived id `uuid5("arv2-project-plan:{turn_id}:{expected_version or 0}")`
**before** anything is rendered, addressed or stored; `current_plan_version` mismatch →
`project_document_revision_conflict` naming `inputs/project/plan.md`; render → content address →
`record_artifact` → `storage.put` → INSERT `ON CONFLICT (document_id) DO NOTHING` with the servable
row as `supersedes_document_id`; the scope-aware unique index's `IntegrityError` →
`project_document_version_race`; the other `ready`/`proposed` rows retired **in this project's
scope only**. `list_project_documents` / `read_project_document` / `save_project_document` (the
human PUT) mirror `frontend_read.brand_knowledge.save_knowledge_document` clause for clause —
`FOR UPDATE` on the row, a `project` row lock, `MAX(version)` vs `expected_revision`, an unchanged
body is a no-op, `user_edit` front matter, `derived_from_document_id` inherited. 9 DB tests.

**T2 — `1a2c8264b` — the tool and the plan part.**
`platform/api/clue_api/project_document_tools.py` (root module, ruling L): the
`ProjectDocumentService` protocol, `DbProjectDocumentService(storage)` (one transaction per call),
and `write_project_document@1` — `document: Literal["plan"]`, `body` (1…200 000),
`expected_version: int | None`, trusted `source_turn_ref`, `pin_requirements=("project",)`, WRITE,
`DOMAIN_IDEMPOTENT` ("presenting turn + document + expected version"), free, no flag.
`_resolve` = `parse_turn_action_ref` → `load_turn_identity` → `submitted_by_user_id` required →
`get_project` in workspace → `project.brand_id`. Tool-level refusals:
`project_documents_not_composed`, `project_document_turn_ref_malformed`,
`project_document_turn_not_found`, `project_document_addressee_missing`; the store's four pass
through as `PreconditionFailed`. Registered **ungranted** (ruling J) in `toolbelt_wiring` /
`agent_registry_wiring`, composed with no flag in `fleet_main.py` and `projections_main.py`.
`conversation_turns._PLAN_OBJECT_TYPES` gains `project_document`; its `emit_plan_part` call titles
it **"Plan"** with `revision_label = f"v{ref.version}"`, so a finalize carrying
`{object_type: "project_document", object_id, version}` in `domain_refs` draws the plan card.
Registry counts 128 → **129** names, 146 → **147** addresses. 11 offline tool tests + the plan-part
case in `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py` (the only `_project_turn_close`
harness in the repo).

**T3 — `345bd0fe1` — the HTTP surface.**
`platform/api/clue_api/frontend_read/project_documents.py` (new), registered in
`frontend_read/app.py` immediately after the research-progress route, with `storage=evidence_storage`
and the router's `allow_local_mutations`. Three routes (wire shapes in
`apps/frontend/docs/api-contracts/projects.md` § "Project documents"). Scope is the store's, so
another project's — or another tenant's — document is **absent**, never refused differently. Title
rule: `project-plan` → `"Plan"`, `audience-persona` → `"Personas — {icp_key}"`, everything else
through `icp_confirmation._title` (imported, not restated, so the ICP gate and this list cannot
title one document two ways). Refusal map: `not_found` → 404 `PROJECT_DOCUMENT_NOT_FOUND`,
`revision_conflict` / `version_race` → 409 `DOCUMENT_REVISION_CONFLICT`, `body_empty` → 422
`DOCUMENT_BODY_EMPTY`, unknown → 409 rather than a 500. PUT auth is the brand-knowledge PUT's,
verbatim: principal → `require("project.write")`; else `allow_local_mutations` →
`"local-development-user"`; else 401. 6 DB tests through the real app, red proven first by
un-registering the routes.

**T9 — `93af298c3` — the grant.** `stage0-interview@v24` (= v23 + new **§6b "Write the plan"**
verbatim from the brief + plan 2's parked M1 §5b wording fix + one tool pin);
`head-of-abm@v47` (= v46 + skill pin v23→v24 + one tool pin); `recipe0-stage0-v25.json` (= v24 +
`write_project_document@1` at all four sites); `CONVERSATION_RECIPE_VERSION = 25`;
`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v47"`; the name granted to `HEAD_OF_ABM` in
`C6_AGENT_TOOL_AUTHORITY`, added to `STAGE0_CONVERSATION_TRIAL_SURFACE.withheld_tools` (a
project-conversation capability), and joined to `stage0_recipe._presenting_turn_project_pin`.
v23 / v46 / `recipe0-stage0-v24.json` are byte-untouched (`git diff --stat` over the three paths is
empty). All digests measured on this tree, not copied. Frontend label
`write_project_document: "Write the project plan"` in `chat-tool-presentation.ts` landed here (R12
keeps the label with the backend; the tab does not).

**T10 (this note) — close-out.** Stack restart, recipe-v25 promotion check,
`apps/frontend/docs/api-contracts/projects.md` § "Project documents",
`platform/api/clue_api/arv2/README.md` § "Project plan document" + the current-version line,
`docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum, this note and its README row.

## Verification run

- T9 gate, run twice with identical failures: `uv run pytest tests/arv2
  tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py
  tests/api/test_toolbelt_wiring.py tests/agents tests/api/test_c8_trial_surface.py
  tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_comprehensive_research_contract.py
  --ignore-glob='*_live.py' -p no:cacheprovider -q` → **1358 passed, 2 skipped, 4 failed**, the four
  being exactly the known pre-existing reds (below).
- Per-task suites green: T1 `tests/arv2/test_project_documents_db.py` (9) +
  `tests/arv2/test_icp_authoring_db.py` (9, unbroken); T2 `tests/api/test_project_document_tool.py`
  (11) + `test_lane_d5_gate_read_and_rich_parts_db.py` (13) + the five `conversation_turns`
  consumers (40); T3 `tests/api/test_frontend_read_project_documents_db.py` (6) + the three
  `app.py` neighbours (7).
- `uv run lint-imports` → **26 kept / 0 broken**; `tests/arv2/test_import_guard.py` → 4 passed;
  ruff format + check and mypy clean on every touched module.
- Frontend: `npx tsx --test src/features/projects/model/chat-tool-presentation.test.ts` → **9
  pass**; `npm run lint` → 0 errors (2 pre-existing warnings in
  `design-editor/engine/scene/canvasOperations.ts`).
- **Known pre-existing reds, not this work** (unchanged from plan 2's note): the design profile's
  model assertion (`openai/x-ai/grok-4.6` from `.env` vs `openai/gpt-5.6-terra`);
  `tests/arv2/test_discovery_driver.py::…not_composed_without_the_flag…`;
  `tests/arv2/test_answer_key_loader_db.py` ×2 (leftover `arv2_research_job` rows on the lane DB);
  `tests/api/test_frontend_write_brand_knowledge.py` ×4 (401 under this lane's auth env);
  two `test_chat_gate_answers_o6_db.py` counts; `test_production_context_s3_db.py::…
  brand_knowledge_index`. `tests/execution/test_recipes.py` stays red on this lane for two unrelated
  reasons (the replay-only v16–v18/v20–v21 version gap vs the test's contiguity assertion, and a
  stale `recipe0-stage0@2` row) — which is why promotion is verified against the live registry.
- No `make check`, no broad pytest with real keys (standing rule: live tests spend money).

## Stack restart and recipe promotion (2026-09-12, close-out)

```
$ ./scripts/dev_stack_san_salvador.sh restart-api   > /tmp/san-salvador_restart.log 2>&1
$ ./scripts/dev_stack_san_salvador.sh restart-workers >> …
$ ./scripts/dev_stack_san_salvador.sh status          >> …
  frontend (3020): UP     design-api (8010): UP
  platform-api (8020): UP     platform-api-2 (8030): UP
  fleet-worker: UP (4 process(es), 3 slot(s) each)
```
Output redirected and read with `tail`, never piped. Semarang's process on **8070 is still alive**;
no other workspace's processes were touched. Zero `"level": "error"` / `Traceback` lines in both API
logs and all four worker logs after the restart.

**Recipe v25 is promoted on the lane DB**, seeded by the workers at boot:

```sql
SELECT r.recipe_key, rv.version,
       (SELECT e.event_type FROM recipe_revision_event e
         WHERE e.recipe_revision_id = rv.id ORDER BY e.seq DESC LIMIT 1) AS latest_event,
       rv.created_at
  FROM recipe_revision rv JOIN recipe r ON r.id = rv.recipe_id
 WHERE r.recipe_key = 'recipe0-stage0' ORDER BY rv.version DESC LIMIT 4;

 recipe0-stage0 | 25 | promoted   | 2026-09-12 15:30:20+00
 recipe0-stage0 | 24 | superseded | 2026-09-12 14:23:49+00
 recipe0-stage0 | 23 | superseded | 2026-09-11 05:45:25+00
 recipe0-stage0 | 22 | superseded | 2026-09-11 05:45:24+00
```
(`recipe_revision` has no `recipe_key`/`status` column — promotion state lives in
`recipe_revision_event`, migration `128c83d5e151`. This is the working form.)

## Rulings taken during execution (ledger)

- **I** — `save_project_document` (the human PUT) demotes a `confirmed` project-local ICP to
  `proposed` exactly like the brand PUT does, dropping `confirmed_by` / `confirmed_at` /
  `confirmed_for_project_id` / `product_selection_version`; a `project-plan` row stays `ready`
  (there is no approval stamp for plans).
- **J** — T2 registers `write_project_document` **ungranted** and composes
  `DbProjectDocumentService(storage)` wherever storage exists, with **no flag** — the same shape
  `author_icp_document` uses. The grant is T9's separate commit.
- **K** — a **fourth** refusal code, `project_document_not_found`, for the human save of a document
  this project does not own (or one in a folder outside `('project','audience')`). Task 3 maps it
  to 404 and `project_document_revision_conflict` to 409; overloading the conflict code would have
  told the editor a lie. A *superseded but existing* document is a conflict, not a 404.
- **L** — the service seam `ProjectDocumentService` / `DbProjectDocumentService` lives in
  `platform/api/clue_api/project_document_tools.py` (the `clue_api` root), calling T1's
  `write_project_plan` in one transaction — turn binding lives outside `arv2/`, so the tool cannot
  live inside it.

Plan 1's ruling **F** (`project_workspace_path` is the one rule mapping a document row path to its
workspace path) is load-bearing here too: T1 restates `inputs/project/plan.md` as a constant with a
comment naming the rule and the guard that forbids the import.

## Deferred — the frontend half (ruling R12)

`docs/superpowers/plans/2026-09-12-plan-tab-frontend.md` keeps the parent plan's task numbers 4–8:
the frontend model/repository/BFF over the three routes, the shared `components/markdown/` pieces
lifted from the Knowledge editor, surface `"plan"` in the chat shell with its tab/pane/editor, the
auto-open signal and the plan-card click-through, and project documents as gallery document cards.
It runs together with the markdown-toolbar slice. Until it runs, the plan card renders in the chat
(title "Plan", `v{n}`) but **does not open anything**, and the `?surface=plan` deep link does not
exist.

## OWED — the live walk (founder-triggered; not run by the implementing agent)

API twins and workers were restarted on this code and recipe v25 is promoted, so v47 / v24 / v25
are live. On the project from plan 2's walk (ICP confirmed and pinned, products confirmed):

- [ ] Ask the agent for the plan once the strategy is settled. `write_project_document` is visible
      in the transcript as **"Write the project plan"**, and the **plan card** appears in the chat
      titled "Plan" with revision label `v1`. (Its click-through is deferred — it opens nothing.)
- [ ] v1 exists and is `ready`, scoped to the walking project:

```sql
SELECT version, status, project_id FROM brand_knowledge_document
 WHERE path = 'project/plan.md' ORDER BY created_at DESC LIMIT 5;
```

- [ ] Edit one line through the human PUT on this lane's API and get v2 `ready` with the `user_edit`
      stamp (`X-Workspace-Id` is this router's tenant seam — `frontend_read/app.py`'s
      `frontend_read_workspace_resolver`; 401 without it):

```bash
curl -sS -X PUT \
  "http://127.0.0.1:8020/frontend/v1/projects/{project_id}/documents/{document_id}" \
  -H "X-Workspace-Id: {workspace_id}" \
  -H "Content-Type: application/json" \
  -d '{ "body": "# Plan\n\n…the edited markdown…\n", "expected_revision": 1 }'
```
      Expect `200` with `data.version == 2`, `data.status == "ready"`, `data.front_matter.user_edit`
      naming the saver; the SQL above then shows v1 `superseded`, v2 `ready`. A second PUT at
      `expected_revision: 1` must answer **409 `DOCUMENT_REVISION_CONFLICT`**, and another project's
      document **404 `PROJECT_DOCUMENT_NOT_FOUND`**.
- [ ] In a **new thread**, ask the agent to add a step. It re-reads `inputs/project/plan.md`,
      **keeps the human's edited line**, and writes **v3** (the SQL shows v2 `superseded`, v3
      `ready`); `inputs/project/status.md`'s Plan line reads version 3.
- [ ] Record the SQL output, the curl responses and a transcript summary back into this note. **Any
      refusal, a lost human edit, or a row whose `project_id` is not the walking project is a defect
      to fix — not something to accept.**
- [ ] Plans 1 and 2's live proofs are still owed (`agent_turn_project_files` — one row, 2 files;
      `author_icp_document` + `request_persona_synthesis`); the same walk can prove all three.

## Follow-ups carried out of the plan

- `project_document_version_race` is implemented and mapped but **not unit-tested** — reaching it
  needs a second committed connection inserting the same `(scope, path, version)` inside the
  window, and the harness has no seam there. Identical to `icp_document_version_race` in plan 2.
- The list route reads **one blob per listed document** for its title, though only `icp-definition`
  actually needs its body. Fine for a handful of documents; the first place to look if a project
  ever owns many.
- `CORS_ALLOW_METHODS` on the `/frontend/v1` router is `["GET", "OPTIONS"]`, so the new PUT is
  same-origin/BFF-only cross-origin-wise — exactly like the brand-knowledge PUT. A decision, not an
  oversight; the deferred Plan tab goes through the BFF.
- `from clue_api.arv2.icp_confirmation import _title` crosses module lines into a private name
  (precedent: `frontend_read/account_workspace` imports `contacts._account_404`). Promoting `_title`
  to a public name is a one-line tidy if a reviewer prefers it.
- `clue_api.arv2.__init__` does not re-export `project_documents`; the tool module imports the
  module path directly, as `icp_authoring_tools` does. Optional tidy.
- **Skill `summary` is at 505 of its 512-character cap.** The next grant that appends a clause to
  `stage0-interview`'s summary will not fit — rewrite it rather than append.
- The plan-part title/label mapping is only tested DB-backed (it lives inside
  `ConversationTurnEngine._project_turn_close`); an offline test needs the mapping extracted to a
  pure helper.
- The lane DB still carries committed rows from earlier walks (`agent_gate_answer`,
  `arv2_research_job`, `recipe0-stage0@2`) behind several pre-existing reds; a reset clears them.

## Final-review fix wave — 2026-09-13 (base `b55a858b2`)

Applied I1, I2 and M1–M8 from `.superpowers/sdd/2026-09-12-project-plan-document/final-review.md`
(adjudication in `progress.md`); full record in that folder's `fix-report.md`.

- **I1** replay key = `turn : expected_version : sha256(body)` — a same-turn rewrite is now a named
  revision conflict instead of a silent discard; an identical retry is still a replay.
- **I2** one lock order for both writers: the `project` row `FOR UPDATE` first (agent: after the
  replay short-circuit, before `MAX(version)`; human: before the document row's `FOR UPDATE`). No
  two-connection deadlock test is achievable with `rollback_conn`; the order is pinned with a
  statement-recording connection wrapper instead — noted in the test's docstring.
- **M1** `_stored_plan` scoped by workspace+project. **M2** `storage.put` after the INSERT/retire in
  both writers (`record_artifact` stays before). **M3** the detail GET serves a superseded version of
  this project with its real status. **M4** new `tests/arv2/test_servable_statuses_agree.py` guards
  the six restated servable tuples. **M5** no blob read for plan/persona titles; `except` narrowed to
  `(StorageError, ValueError)`. **M6** the human PUT is gated by kind, not folder. **M7** the plan's
  front matter carries `version` on both write paths. **M8** a no-op INSERT reports `replayed=True`.

Gates: the five named suites pass (41), ruff format/check clean, mypy clean on the three touched
modules, `lint-imports` 26/0. Each item has a test proven RED against its own revert.
`platform/api/clue_api/arv2/read_tools.py` deliberately untouched (parallel plan-4 review).
**Still owed:** the live walk (I3) — unchanged by this wave.

## Final review + fix wave (2026-09-13)

Opus whole-plan review: 0 Critical / 3 Important / 8 Minor / 6 Nit. Fix wave `5547c3e10`: the plan's
replay key now includes the body digest (a second same-turn write is a real write, or a revision
conflict); both writers lock the project row first (`_lock_project`) so the agent write and the
human PUT cannot deadlock; the replay read is scoped; the blob is stored after the row in both
paths; the detail GET serves a superseded version of this project with its real status (the editor
can rebase); the human save is gated by kind (plan, ICP, persona); the plan's front matter carries
`version:` (ruling P) so skill §6b's "the version of the file you read" is literally in the file; a
no-op INSERT reports `replayed=True`; a drift-guard test pins the servable-status tuples equal
across the six modules that restate them. I3 = the owed live walk.
