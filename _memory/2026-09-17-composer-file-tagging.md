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
