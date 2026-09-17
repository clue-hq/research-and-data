# 2026-09-17 — Composer `@` tagging of files, microsites and accounts

## State at end of session (planning only; execution NOT started — founder ruling)
- Clipping bug fixed and verified: the `@` picker mounted with every account but
  `.composerEditorShell { overflow: hidden }` clipped it. Commit `89f34dd4e` (shell overflow
  visible; the editor is the scroll container). Details in `2026-09-12-composer-layout.md`.
- Design spec approved: `docs/superpowers/specs/2026-09-17-composer-file-tagging-design.md`
  (commit `ac86afa11`). Rulings: categories Files / Microsites / Accounts; scene ads and tables
  under Files; Gallery is the file system, no path or id in the UI; a tagged design artifact is a
  reference only, Head-of-ABM decides by reasoning whether to open a design leg; picker offers
  latest versions only, a tag pins the version; typing searches all categories, empty query
  browses; no side effects on tag; spaces allowed in the query with self-close on no match; Home
  composer keeps the flat accounts list; no profile-text change in the first cut.
- Implementation plan written and committed: `docs/superpowers/plans/2026-09-17-composer-file-tagging.md`
  (commit `a62256efc`), 8 tasks: wire + CHECK migration; validation + project containment; focus
  card; transcript echo; frontend models + catalog; wiring; two-level picker; chips + docs.
- Verified facts the plan relies on (2026-09-17): routing reads only the open design leg
  (`agent_turn_fleet_wiring.py:433-441`), refs play no part; the `design_document` focus card
  already exists; each project-document version is its own row with its own id
  (`arv2/project_documents.py:239`); alembic head `e8fdb29cd532`.
- One spec deviation ruled in the plan's self-review: `design_document` version stays optional
  on the backend (fresh documents are v0); `project_document` version is mandatory.

## Next
- Founder says when to execute (SDD: Opus implementers, Fable plans/reviews/verifies).
- Owed after execution: live proof of the L5 card in a real turn; live microsite mention
  answered without a leg (Task 8 extends this note).

## 2026-09-17 (later) — hangzhou lane ports
- This checkout (`hangzhou`, branch `research-streaming-v3`, cut from `research-streaming`) is the
  execution lane for the plan. Its `.env` / `apps/frontend/.env.local` were repointed so the stack
  can run beside san-salvador's live 3020/8010/8020/8030 stack: **frontend 3050, platform API 8090,
  design API 8091** (`CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, `CLUE_API_BASE_URL`,
  `LUMEN_API_BASE_URL`, `CLUE_APP_ORIGIN`; 3050 added to `LUMEN_API_CORS_ORIGINS` and
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`). DB stays `clue_hangzhou` on :55040.
- `scripts/dev_stack.sh` gained four port knobs (`DEV_STACK_FRONTEND_PORT` / `_DESIGN_PORT` /
  `_PLATFORM_PORT` / `_PLATFORM2_PORT`, defaults = the runbook ports, so istanbul and every other
  wrapper are unchanged) and **`scripts/dev_stack_hangzhou.sh`** sets them to 3050/8091/8090/8092,
  one worker × one slot, logs `/tmp/hangzhou_*.log`. The wrapper refuses to start unless `.env` and
  `apps/frontend/.env.local` name the same ports (proven in a sandbox: matching env execs; a
  drifted `CLUE_APP_ORIGIN` or a missing 3050 in the Clerk parties exits 2). Runbook section added
  to `DEV_STACK.md`. The stack has NOT been brought up yet.

## 2026-09-17 (execution) — the eight tasks landed
Lane: this checkout (`hangzhou`), branch **`file-tagging`** (renamed from `research-streaming-v3`
mid-session; cut from `research-streaming`). Migration **`9289d41e9a60`**, chained off
`e8fdb29cd532`.

### Commits
- `13354456a` Task 1 — wire + CHECK migration (`project_document` added to the context-ref
  vocabulary at every submission surface).
- `d169cb458` Task 2 — validation: project containment, latest-version pinning, the Home refusal.
- `dad34bbc5` Task 3 — the L5 focus card for a tagged project document.
- `5f4ad9a65` Task 4 — transcript echo (`label` + `kind` resolved at read time).
- `eca3d1084` Task 5 — typed composer entities, the file/microsite/account catalog, cross-category
  search.
- `c46aa418f` Task 6 — feed the catalog with Gallery files and microsites; resolve transcript chips
  from it.
- `a0307a467` Task 7 — the two-level `@` picker (Files / Microsites / Accounts).
- Task 8 (this commit) — typed chips in composer and transcript, the contract notes in
  `apps/frontend/docs/api-contracts/projects.md`, and this note.

### Rulings
The spec's approved rulings stand (categories **Files / Microsites / Accounts**; scene ads and
tables under **Files**; the Gallery is the file system and **no path or id is ever shown**; a
tagged design artifact is a **reference only** and never opens or routes a design leg — Head-of-ABM
decides that by reasoning; the picker offers **only the latest version** and a tag **pins the
version** it was sent with; **typing searches across all categories**, an empty query browses by
category; tagging does **not** open the item's Gallery tab; the **100 refs per turn** cap stays; an
empty category shows one line; spaces allowed in the query with self-close on no match; the Home
composer keeps the flat accounts list; no profile-text change in the first cut).

Three further rulings taken during execution:
1. A superseded `project_document` row refuses as **`CONTEXT_REF_STALE`**, never
   `CONTEXT_REF_NOT_FOUND` — `get_project_document` reads any status and staleness is the
   validator's call (spec §3.2 / acceptance 5).
2. `design_document` version stays **optional on the backend** (a fresh design is v0); the frontend
   omits v0 artifacts from the picker. `project_document` versions are mandatory.
3. The transcript echo reads the document with **`servable_only=False`**, so an older turn keeps
   naming the title it was tagged with.

### Verified
Tests — backend `tests/api/test_project_document_context_refs_db.py` (4 DB tests) and
`tests/api/test_chat_composer_context.py` (+4 unit tests); neighbouring suites green (p31 design
vocabulary, reference images, lane_d2 submission, thread shell, frontend-read project documents).
Frontend `npm test` 2,295 passing at Task 7, `composer-context-catalog.test.ts` (4 tests), lint and
build green. One pre-existing red unrelated to this work:
`tests/api/test_home_project_bootstrap_db.py::test_home_read_is_real_scoped_and_capability_honest`
(model-label drift, Grok 4.6 vs GPT-5.6 Terra).

Browser (hangzhou stack on 3050, dev login, a project of the lane workspace): `@` shows
"Files 6 / Microsites 0 / Accounts 105"; Files lists six titled rows with kind labels and no paths;
Back / ArrowLeft / Backspace-on-empty return to the categories; Microsites shows "No microsites
yet"; `@plan` groups two matches under a "Files" header; Enter inserts a chip titled
"<title> · Plan"; ` @zzqx ` auto-closes; Escape closes; the Home composer shows the flat accounts
list (105 options, no category rows); a DOM scan found no path or uuid anywhere in the picker. The
copied lane DB holds no design documents, so ads and microsites were not exercised live.

### Owed (founder-triggered, NOT run)
1. A live turn tagging a file, proving the persisted `project_document` ref and the L5 focus card
   `context/focus/project_document-<hash>.md` naming `project/plan.md` (acceptance 3).
2. A live microsite mention answered by Head-of-ABM **without** a leg being opened, and a
   "change the headline" message where it opens one by reasoning (acceptance 4).
3. A live stale-tag refusal surfacing the composer's stale-ref message (acceptance 5; unit- and
   DB-proven only).

### Deferred minors
- The focus-card read in `account_research_turn_wiring.py` still uses `servable_only=True`, so at
  replay of a superseded version the title falls back to the file name.
- `useProjectDocumentTabs` and the chat surface each fetch the document list (double-fetch).
- Three pre-existing `tsc` errors plus the ungenerated `.next/types` baseline.

### Lane setup done this session
`scripts/dev_stack_hangzhou.sh` brought up on 3050 / 8090 / 8091 / 8092 (the port knobs added to
`dev_stack.sh`); `clue_hangzhou` is a copy of `clue_san-salvador` plus a copy of its `.artifacts`;
one `auth_identity` row was inserted on the lane DB so the dev login maps to the workspace owner.
