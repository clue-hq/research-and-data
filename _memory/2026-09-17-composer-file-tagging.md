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

### Final-review fix (2026-09-17, after Task 8)
- `6db54fdf1` — the `project_document` focus card now reads the document with `servable_only=False`
  (same ruling as the transcript echo), so a replayed turn whose tagged version was later superseded
  still carries the tagged title; pinned by an added assertion in
  `tests/api/test_project_document_context_refs_db.py`. The "deferred minor" about this above is closed.
- Whole-branch gates re-run by the controller after all eight tasks: 7 backend suites 61 passed, ruff +
  mypy clean on the 7 changed modules, one alembic head `9289d41e9a60`; frontend 2295/2295, lint 0
  errors, build green. The hangzhou stack was left running for the owed live proofs.
- 2026-09-17 (later): founder ruling 'stick to grok-4.6 only' — the pre-existing red `test_home_read_is_real_scoped_and_capability_honest` was expectation drift; it now expects the Grok 4.6 profile (label/short_label/description/model_id `x-ai/grok-4.6`). Commit follows f71e33239.

### Composer logos (2026-09-17, founder ask after the file-tagging walk)
- Every account/contact row in the `@` picker showed a broken image: the backend never filled
  `image_url` and the frontend fell back to `/logos/clue.svg`, which never existed in
  `apps/frontend/public` (fallback dated 2026-08-13, pre-existing). Commit `ebd8f8713`: accounts
  carry `account_logo_path(...)` (the platform's logo route for a stored LinkedIn mark, else
  Brandfetch's Logo API for the domain) read once per catalog page through `_account_logo_urls`;
  `settings` threaded from the chat router; the frontend accepts a rooted path or the
  `https://cdn.brandfetch.io/` origin only (`composerEntityImagePath`), renders the building glyph
  when there is none, and draws a contact's initials with the accounts feature's `ContactAvatar`
  (picker + composer chip). Gates: composer-context unit + home-bootstrap DB suites green, ruff,
  mypy; frontend 2295/2295, lint, build.
- Finding: Brandfetch's CDN answers a `HeadlessChrome` user agent with a 302 to its hotlinking
  guidelines (so gstack browse shows `naturalWidth 0` on every Brandfetch logo, on the accounts
  list too); a real Chrome UA gets `200 image/webp`. Set `browse useragent "<Chrome UA>"` before
  any logo check. The platform's own logo route (stored marks) renders in both.

### Accounts tree in the `@` picker (2026-09-17, founder ask; rulings: search stays flat, tagging an account never tags its contacts)
- Contacts now nest under their account: the wire entity gained `account_id` + `account_name`
  (both builders in `composer_context.py`, `ComposerContextEntityWire`, router passthrough); the
  frontend maps them to `ProjectEntity.accountId/accountName`. `accountTreeRows(catalog, expanded)`
  (accounts in order, each followed by its contacts only while expanded; a contact whose account
  is not in the catalog trails flat), `contactCountsByAccount`, and `composerCategoryCounts`
  counting accounts only. Editor state `expandedAccountIds` (reset on close): ArrowRight unfolds
  the highlighted account (when it has contacts), ArrowLeft folds from the account or from a
  contact (highlight lands on the account), then falls through to "back to categories";
  Enter/click on the account row tags the account whether or not it is open; the fold control is a
  separate button beside the row (`.entityRow`/`.entityExpand`, nested rows indented). Search
  results stay flat with `| <account name>` beside a contact. Home composer shows the same tree.
- Verified in the browser on the hangzhou stack: 50 accounts, 12 with fold controls; Baylor's 5
  contacts unfold on ArrowRight and on the chevron click (no tag); Enter on the open account tags
  the account; Enter on a nested contact tags the contact; ArrowLeft folds and lands on the
  account, a second ArrowLeft returns to the categories; `@walter` shows one flat row with the
  account beside it; Home shows the same tree. Also fixed the same session: the active row now
  scrolls into view while arrowing (`c7bf3c61c`).
- Incident: a stray Enter with the picker closed SENT "@Baylor Scott & White Health" to the
  thread (one live Head-of-ABM turn on the lane DB); the stack was restarted for the build gate
  while it ran, so the turn ends failed/unsaved. No other side effects.
- Note: the platform API is not `--reload`; a backend change needs
  `./scripts/dev_stack_hangzhou.sh restart-api` (run it in the background — a foreground timeout
  kills the freshly started servers).

- PR: https://github.com/clue-hq/research-and-data/pull/61 (`file-tagging` → `research-streaming`, opened 2026-09-17; 19 commits, 40 files). The workspace's configured target `integration/design-improvement` is an ancestor of `research-streaming` and was deliberately not used.
