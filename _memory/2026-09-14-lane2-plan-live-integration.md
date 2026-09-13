# Lane 2 Plan tab live integration — 2026-09-14

- Founder approved production Plan integration after preview 756a4ff9a. The ambiguous latest
  “step 5 after step 5” was resolved by its Plan-tab annotation and the prior preview checkpoint.
  Work is in Semarang `visual-polish`, active plan Tasks 6–7; Task 8 remains separate.
- Added Plan to shell/URL vocabulary, third tab, empty/loading/error/document pane, shared
  MarkdownArticle/MDXEditor, permission-aware Preview/Edit and Save/Discard. Changes stay in
  frontend models/hooks/data seams; backend document contracts unchanged.
- Extracted Knowledge's existing draft/revision session into shared markdown model/hook;
  Knowledge is a thin adapter. Plan keys sessions by workspace/project/path, retains drafts on
  tab switches and dirty external refreshes, and adopts the saved immutable ID for the next save.
  Abortable browser list/detail reads share the BFF request/error helper with saves.
- Plan card titles open the tab. New project_document plan parts open/refresh it once;
  initial and paginated older history do not. No dependency on a particular tool name.
- Semarang runtime: inspected isolated DB, applied checked-in migrations 6c54be5199c8,
  b953bf11e2a9, merge 98775241f1e5 from old d639a2de8bd1. Reloaded only owned platform API
  (new PID 55052, port 8070) using launcher-validated environment. No other server/process
  stopped; .env settings unchanged. Worker processes were not reloaded.
- Real browser on 3040: empty Plan in existing project; disposable project's stored Markdown;
  opening Edit left Save disabled; source/rich edit; two successful saves; draft survives
  Gallery/Plan switching. DB/artifact proof confirmed immutable v1→v2→v3 and body markers.
  Separate store write created v4; stale human-save request correctly refused without overwrite.
- The browser session expired during reload verification. Sign-in recovery was attempted;
  normal /onboarding/sign-in is available. Founder was asked asynchronously to sign back in.
  Auto-review rejected a proposed lookup of the test user's email as private account data;
  it was not executed or bypassed. Browser reload/conflict/keyboard/narrow-layout and live
  plan-part/card walkthrough remain unverified. Do not claim those passed or a live model turn.
- Removed only the disposable test project's thread/documents/project after verification;
  content-addressed artifact evidence remains local. User's project content was untouched.
- Checks: 2,262 tests pass using `rg --files src -g '*.test.ts' -0 | xargs -0 node --import tsx
  --test`; npm test's tsx CLI initially failed on sandbox IPC socket EPERM. Token build and
  production Next build pass. Lint passes with 2 existing unused-function warnings in
  canvasOperations.ts. Standalone tsc includes existing test-fixture errors; production build's
  app typecheck passes. Initial test caught Plan URL missing; later test incorrectly expected
  generic panel toggle to reopen Plan (existing Gallery behavior preserved; explicit Plan opens).
- React checklist reviewed: lazy shared editor, primitive fetch effect dependencies, abort on
  inactive/project changes, immutable version adoption, permission-driven editing, no transport
  in presentation. No new dependency, backend implementation or env flag.
- Closing: frontend implementation complete and local commit only. Remaining acceptance needs
  an authenticated browser; next implementation is Gallery ICP/persona document cards (Task 8).

## Login follow-up

- Founder supplied a test login directly. Normal email/password sign-in and Clerk's documented
  test-email verification succeeded; credentials were not written to files.
- Opening the existing Semarang project redirects to profile setup. The session DAL routes
  an unprovisioned identity or an identity without workspace membership there. The test login
  therefore does not yet provide access to the project needed for the remaining browser checks.
- Asked the founder to complete setup/open the intended workspace or use its existing test
  account. Did not create a workspace, alter memberships, or bypass authentication.
- Confirmed the previous disposable Plan fixture has no remaining document rows. No fresh
  fixture was created. Implementation, environment settings, and running processes unchanged;
  reload/conflict/keyboard/narrow-layout/live-plan walkthrough checks remain pending.

## Resumed verification and replay correction

- Replacement test login reached the existing workspace normally. No credentials were stored.
- Disposable project browser checks passed: saved content survives full reload; stale save keeps
  the draft; Check for updates preserves it; Discard adopts latest; saving on that revision works.
  Keyboard Arrow/Home/End navigation works. Preview/Edit at 720 and 390 px contain long inline
  code, fenced blocks, and tables without widening the page; viewport override reset afterward.
- No-model stream fixture used the existing submission/outbox/Plan emitter on the disposable
  thread, with a transactional queue hold preventing dispatch. Plan card click, new part auto-open,
  duplicate stability passed. An initial fixture ref incorrectly used a dict instead of the
  emitter's typed DomainObjectRef; corrected the fixture, not production code.
- Cold replay exposed a real defect: plan parts arrive after initial loading ends, so the old
  transcript-snapshot baseline reopened Plan over Gallery. Replaced it with a projects-model
  ProjectPlanWriteTracker, seeded from the first server lastEventId for each turn before attach.
  Controller exposes planWriteRevision; shell consumes it. Keep cursors across reconnects, seed
  newly submitted turns at zero, deduplicate by part ID. No client clock or new transport contract.
- Verified corrected cold replay keeps Gallery and a subsequent new document part still opens
  Plan. Added five regression tests replacing the three old snapshot tests. All 2,264 tests pass;
  token build, lint (two pre-existing warnings), and production build pass. First targeted test
  run failed as expected before the new model existed. React checklist and scoped diff reviewed.
- Cleanup initially hit the append-only control-record trigger; transaction rolled back. Did not
  bypass the trigger. Archived only the disposable project/thread instead, retaining audit rows,
  document versions, and the protective queue hold. Both fixture streams are terminal and a
  scoped query confirmed zero fleet tasks. No real provider calls, server restarts, or env edits.
- Closing: Tasks 6–7 browser acceptance complete using actual document APIs and controlled live
  streams; this does not claim a real model-generated turn. Task 8 remains separate. Local commit
  only; leave the existing user's Plan tab open for testing.
