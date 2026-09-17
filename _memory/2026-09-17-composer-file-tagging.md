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
