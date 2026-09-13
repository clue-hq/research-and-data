# 2026-09-12 — ICP authoring (plan 2 of the context + ICP-authoring set)

Branch `research-streaming`, worktree `san-salvador`, lane DB `clue_san-salvador`. Plan
`docs/superpowers/plans/2026-09-12-icp-authoring.md`; spec
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.2. SDD ledger
and per-task reports: `.superpowers/sdd/2026-09-12-icp-authoring/` (git-ignored).
Base `47e9e08b6` (plan 1's close-out). Commits `0d96ab62f`, `ad756321d`, `c28454890`, `885c246f2`,
`311b4e51c`, `ab590794d`, and this close-out.

## The problem it solves

A marketer who read the onboarding walk's ICP proposals and said *"none of these is who we sell
to"* had nowhere to go: `synthesize_icps` only ran inside the brand's onboarding walk. Now the Head
of ABM can **write a profile down** in the conversation (brand-level, or local to one project of the
same brand) and can ask for the **personas** of a profile the human has confirmed.

## What shipped, per task

**T1 — `0d96ab62f`, migration `b953bf11e2a9`** (`down_revision = 6c54be5199c8`, plan 1's).
`brand_knowledge_document` + `project_id` (NULL = brand knowledge; composite FK
`(project_id, workspace_id) → project`) and `derived_from_document_id` (self-FK, lineage not
currency); the path/version UNIQUE replaced by the scope-aware unique index
`brand_knowledge_document_scope_path_version (workspace_id, brand_id, COALESCE(project_id, ''),
path, version)`; a partial project index; `'project'` in the folder CHECK, `'project-plan'` in the
kind CHECK. `onboarding_run` + `kind text NOT NULL DEFAULT 'full'` (`full|personas`), `project_id`,
`persona_icp_document_id`, welded by `onboarding_run_persona_shape`
(`(kind='personas') = (persona_icp_document_id IS NOT NULL)`) + a one-open-run partial index.
Reversible, round-trip proven. `alembic heads` = one head; lane DB left at head.

**T2 — `ad756321d` — the reader rule.** Brand readers filter `project_id IS NULL`
(`current_knowledge_documents`, the five onboarding-walk reads in `onboarding_store`, every
`frontend_read/brand_knowledge` read incl. the PUT's `FOR UPDATE`/`MAX(version)`; the
`IntegrityError` name follows the index rename). Project readers union and let the project win:
new `current_project_knowledge_refs(conn,*,workspace_id,project_id)`;
`current_icp_document(..., project_id=)` selects `(project_id IS NULL OR project_id = :p)` and
orders `path, (project_id IS NULL), version DESC`. `confirm_icp_document` mints the next version in
the *subject's* scope (`IS NOT DISTINCT FROM`) carrying `project_id` + `derived_from_document_id`;
`KnowledgeDocumentRef` / `IcpDocumentSubject` / `ProjectIcpPin` / `RegisteredIcp` carry the scope.
`workspace_paths` groups by `(project_id, path)` and resolves a project ref through
`project_workspace_path`; `knowledge_seed_files` skips project refs (plan 1's project-files pin owns
`inputs/project/`). Two readers found outside the brief: `chat/router.py` ~1968 (gate-answer
revalidation — unscoped it 409'd `GATE_SUBJECT_STALE` on a project-local approve) and
`account_research_store.read_persona_documents` (scoped `IS NULL OR = :p`, threaded from
`run.project_id`).

**T3 — `c28454890` — `author_icp_document@1`.** `arv2/icp_authoring.py` (the write) +
`icp_authoring_tools.py` (the tool, at the `clue_api` root because turn binding lives outside
`arv2/`). WRITE, `DOMAIN_IDEMPOTENT`, free, no flag. Document id
`uuid5("arv2-icp-authoring:{turn}:{scope}:{key}")` → a replay inside one turn returns the stored row
before anything is rendered (`authored_at` is the one non-deterministic byte). Born **`proposed`** —
authoring proposes, the human's confirmation gate decides. Platform front matter (`status`,
`brand_id`, `project_id`, `derived_from`, the confirmation stamp, `product_selection_version`,
`user_edit`) is stripped from what the model typed and re-stamped from resolved rows. Supersede is
scope-local and never retires a `confirmed` row. Refusals: `icp_key_invalid`,
`icp_front_matter_invalid`, `icp_key_taken_by_brand`, `icp_key_taken_by_project` (only a *servable*
row owns a key), `derived_from_not_found`, `icp_document_version_race`, plus
`authoring_turn_ref_malformed` / `authoring_turn_not_found` / `authoring_addressee_missing` /
`icp_authoring_not_composed`. Registered ungranted.

**T4 — `885c246f2` — `request_persona_synthesis@1`.** `persona_request_tools.py`; SPEND,
`DOMAIN_IDEMPOTENT`, composed behind `onboarding_v2_enabled` (what it opens *is* an onboarding run;
with the lane off the row would hold that document's one open slot forever). Checks the project's
**pinned** ICP key, then offers a personas-only run through `DbOnboardingEnqueuer` (one place knows
the task shape). `persona_run_id = uuid5("arv2-persona-run:{ws}:{document_id}:{turn}")`. Store gains
`create_persona_run` / `open_persona_run`; `read_current_run` and the `POST /onboarding` 409 both
filter `kind = 'full'`. Driver `_personas_only`: `mark_run_running` → one `_persona_step` →
`finish_run`, in the ICP's own scope (`IcpRef.project_id`). `_current_input_documents` unions the
ICP's project over the brand so the persona turn can read the document it was asked about. Refusals:
`persona_synthesis_not_composed`, `icp_not_pinned_for_project`, `persona_run_already_open`,
`brand_not_onboarded`, `enqueue_failed` (leaves the run `failed`, so the document is free again).

**T5 — `311b4e51c` — materialization.** `project_status.current_project_documents` compiles the
project's knowledge rows onto the lease (verified bytes, digest mismatch → `ProjectFilesPinConflict`)
and `load_project_status_facts` lists them under *Project documents* off the same read, so
`status.md` cannot name a file the turn does not seed. It lives in `project_status.py`, not
`project_context_files.py`, to keep the import direction one-way. `summary_of` now skips a leading
front-matter block (every authored document starts with `---`).

**T6 — `ab590794d` — the grant.** `stage0-interview@v23` (§1 `inputs/project/` bullets, §3 outcomes,
§5 *Revised*, new **§5b "Author a profile"** and **§5c "Personas for a confirmed profile"**, §10),
`head-of-abm@v46` (skill v23 + both tool pins), `recipe0-stage0-v24.json` (both addresses at four
sites), `CONVERSATION_RECIPE_VERSION = 24`,
`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v46"`, both tools on
`STAGE0_CONVERSATION_TRIAL_SURFACE.withheld_tools`, both granted to `HEAD_OF_ABM` in
`C6_AGENT_TOOL_AUTHORITY`, both pinned via `_presenting_turn_project_pin`. All digests measured on
this tree. v22 / v45 / recipe v23 byte-untouched.

**T7 (this note) — labels + docs.** `chat-tool-presentation.ts` `TOOL_LABELS`:
`author_icp_document → "Draft an ideal customer profile"`,
`request_persona_synthesis → "Write the buyer personas"`, with a test that both render as operator
work and leak no receipt data. Lane docs: `platform/api/clue_api/arv2/README.md` § "ICP authoring and
project-scoped documents"; `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum.

## Verification run

- Frontend: `npx tsx --test src/features/projects/model/chat-tool-presentation.test.ts` → **8
  passed**; `npm run lint` → 0 errors (2 pre-existing warnings in
  `design-editor/engine/scene/canvasOperations.ts`).
- T6 gate, twice, identical: `tests/arv2 tests/api/test_agent_registry_wiring.py
  tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py tests/agents
  tests/api/test_c8_trial_surface.py tests/api/test_client_knowledge_privacy_s4e.py
  tests/api/test_comprehensive_research_contract.py --ignore-glob='*_live.py'` →
  **1342 passed, 2 skipped, 4 failed** — all four known pre-existing (below).
- Per-task suites green: T1 db migration tests (5 + the repaired substrate guard), T2 `9 failed,
  1096 passed` vs a stashed baseline `9 failed, 1093 passed` (identical failure set, +3 new), T3
  `tests/arv2/test_icp_authoring_db.py` (9) + `tests/api/test_icp_authoring_tool.py` (11), T4
  `test_persona_run_db.py` (9) + `test_persona_request_tool.py` (10) + the routes/synthesis pair
  (10), T5 the four project-context/composition files (24).
- `uv run lint-imports` → 26 kept / 0 broken; `tests/arv2/test_import_guard.py` → 4 passed;
  ruff + mypy clean on every touched module.
- **Known pre-existing reds, not this work** (each attested by re-running stashed): the design
  profile's model assertion (`openai/x-ai/grok-4.6` from `.env` vs `openai/gpt-5.6-terra`);
  `tests/arv2/test_discovery_driver.py::…not_composed_without_the_flag…` (the real key leaks into
  the keyless fixture); `tests/arv2/test_answer_key_loader_db.py` ×2 (leftover `arv2_research_job`
  rows on the lane DB); `tests/api/test_frontend_write_brand_knowledge.py` ×4 (401); two
  `test_chat_gate_answers_o6_db.py` counts that read `agent_gate_answer` without a workspace filter;
  `test_production_context_s3_db.py::…brand_knowledge_index`. `tests/execution/test_recipes.py` is
  red on this lane for two unrelated reasons (the replay-only v16–v18/v20–v21 version gap, and a
  stale `recipe0-stage0@2` row with a different definition) — recipe v24's promotion was therefore
  verified directly against the lane registry instead (`24 promoted`, `23 superseded`).

## Standing rule (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`) — 7/7 run

1. Profile grants — v46 pins no readiness / Stage-0 / Client-KB / Product-KB tool. ✔
2. Gate source — untouched; neither new module calls `compile_client_knowledge_card_v2`,
   `current_kb_version` or `load_pinned_client_knowledge` (grepped). ✔
3. Scope pin content — both tools use `_presenting_turn_project_pin` off the trusted
   `source_turn_ref`; no Client-KB pin, no new `AgentTurnScopePinConflict` path. ✔
4. Context composition — a project document is a read-only materialized `.md` + an index row; no
   card compiler runs. ✔
5. Launch path — `launch_arv2_account_research` gained no precondition. ✔
6. Static guard — import guard green, `lint-imports` 26/0. ✔
7. `.env.example` posture unchanged; **no new flag** (`author_icp_document` needs none;
   `request_persona_synthesis` rides `onboarding_v2_enabled`). ✔

## Rulings taken during execution (ledger)

- **D** — plan 2's migration chains off plan 1: `down_revision = "6c54be5199c8"`.
- **E** — a personas request against a brand with no completed `full` walk refuses
  `brand_not_onboarded` (the run needs that walk's `company_domain`).
- **F** (taken in plan 1, load-bearing here) — `project_workspace_path` is the ONE rule mapping a
  document row path to its workspace path; T2 imports it rather than restating a prefix.
- **G** — `brand_knowledge_context` imports `project_workspace_path` from `project_context_files`
  (verified no cycle, `lint-imports` 26/0); the brief's "define `PROJECT_INPUT_PREFIX` in
  `brand_knowledge_context`" is superseded.
- **H** — a model-typed front-matter `version:` is advisory; the row's `version` column is
  authoritative everywhere (the same property `onboarding_synthesis._register_documents` already
  has). No change; stamping it would widen the lineage race window.
- **FW1** (fix wave, T4) — `DbPersonaRequestService.request`: when `open_persona_run` is `None` but a
  row already exists under this turn-derived `run_id` (failed/finished), refuse
  `persona_run_settled` ("ask again on a new turn") rather than re-offering a settled row.

## OWED — the live walk (founder-triggered; not run by the implementing agent)

API twins and workers were restarted on this code (see below), so v46/v24 are live. The walk, on a
**fresh project of the founder's brand**:

- [ ] Interview → say the proposals do not fit → the agent drafts. `author_icp_document` is visible
      in the transcript as **"Draft an ideal customer profile"**.
- [ ] The confirmation gate card appears; approve it.
- [ ] The next turn's index card and `inputs/project/status.md` name the new ICP (under *Project
      documents* when the scope is `project`).
- [ ] The agent offers personas; accept → `request_persona_synthesis` shows as **"Write the buyer
      personas"**.
- [ ] A `personas` onboarding run appears and finishes, and the persona document lands in the ICP's
      scope:

```sql
SELECT run_id, kind, status, persona_icp_document_id
  FROM onboarding_run ORDER BY requested_at DESC LIMIT 3;

SELECT document_id, path, version, status, project_id, derived_from_document_id
  FROM brand_knowledge_document WHERE project_id IS NOT NULL
  ORDER BY created_at DESC LIMIT 5;
```

- [ ] Record the SQL output and a transcript summary back into this note. **Any refusal, or a row
      whose `project_id` is not the walking project, is a defect to fix — not something to accept.**
- [ ] Plan 1's live proof (`agent_turn_project_files` — one row, 2 files) is still owed too; the same
      walk proves both.

## Follow-ups carried out of the plan

- `icp_document_version_race` is implemented but untested — reaching it needs a writer landing
  between the lineage `SELECT` and the `INSERT`, and the harness has no seam in that window. The
  unique index is the arbiter; the `IntegrityError` branch re-raises anything else.
- An orphan artifact is possible on that race branch (`record_artifact` + `storage.put` precede the
  INSERT) — the same shape as `confirm_icp_document`; the roots run `run_orphan_blob_sweep`.
- `frontend_read/brand_knowledge._resolve_brand`'s newest-run fallback has no `kind` filter
  (harmless: a personas run can only name an already-onboarded brand).
- A project document whose materialized path collides with `status.md`/`decisions.md` is a permanent
  turn refusal (`ProjectFilesPinConflict`); the *writers* keep paths folder-qualified.
- `frontend_read/brand_knowledge`'s PUT still inserts brand-level rows only; nothing project-scoped
  reaches it today (it filters `folder IN ('company','product','audience','proof')`).
- The lane DB carries committed rows from earlier work (`agent_gate_answer`, `arv2_research_job`,
  `recipe0-stage0@2`) behind several of the pre-existing reds; a reset would clear them.

## Final review + fix wave (2026-09-12, later)

Opus whole-plan review: 0 Critical / 4 Important / 8 Minor / 6 Nit. Fix wave `92cf5cc84` applied I1–I4,
M3–M8: `status.md`'s Confirmed ICP path follows the pin's scope; a pinned project-local ICP is seeded
under the plain name beside its newer version (`audience/icp-<key>.v<n>.md`); the authoring receipt's
`workspace_path` applies the same pin rule; a settled persona run answers `replayed=True` (completed)
or `persona_run_settled` (failed) instead of `enqueue_failed`; `status.md` gains a `## Personas`
section; the brand index card lists brand rows only; the product-set gate's catalog is brand-only;
`storage.put` happens after the INSERT on the authoring path; README states lineage is re-checked
against the reader's workspace. Parked: M1 (skill §5b key wording — lands in plan 3's skill v24:
"keep the existing key for a brand-level revision"), M2's staleness bound on open persona runs, nits.
Two `test_chat_gate_answers_o6_db.py` tests are red on this lane DB only because of four
`agent_gate_answer` rows from live walks (they assert a global zero count) — not this work.
