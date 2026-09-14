# Lane 2 Gallery documents and toolbar acceptance

- Founder authorized remaining steps 5–6: plan-tab Task 8, shared toolbar plan, and
  complete cross-surface verification. Work in Semarang visual-polish only; preserve
  environment and all sibling processes. Local checkpoints, no remote publication.
- Read lane index, Task 8, toolbar plan/spec, frontend architecture, shared editor
  and previous acceptance notes. Existing foundation already composes all requested
  controls; finish extraction/audit rather than reinstalling or replacing it.
- Gallery documents will retain their own typed model, with no manufactured design
  artifacts, thumbnails, account attribution or dimensions. One browser list read
  shared by Gallery and document surface keeps newly saved versions current, via
  the already-approved BFF/repository seam. Document identity in the URL uses stable
  path; the versioned API still uses the returned immutable ID/revision.
- New founder ruling: no permanent Plan/Documents tab. Gallery includes all three
  Markdown kinds. Clicking a card or a fresh agent document-write reference opens
  a named tab; design files follow creation/update events too. The existing internal
  `surface=plan` alias stays for compatibility; `document=<stable path>` selects a file.
  Arbitrary file formats, new document kinds and backend title/rename rules remain out
  of scope. This supersedes the old plan-only tab and plan-card exclusion.
- Browser checks so far: ICP/persona saves persist; draft and native undo/redo survive
  file switch/close/reopen; conflict retains draft until explicit Discard; library
  source recovery retains unsupported JSX and blocks Save. CodeMirror virtualizes
  long source, so innerText alone cannot prove the full source; short JSX fixture did.
  390 and 720 px long-code/URL checks show page width equals viewport.
- First production build caught a nullable plan-reference ID; guarded it and added a
  regression test. Subsequent build passes. Baseline suite passed 2,268 before that
  test; final gates and remaining browser acceptance pending.

- Final checks: 2,270 tests pass via node --import tsx --test (tsx CLI IPC was sandbox
  denied); token build, lint (two existing canvas warnings) and production build pass.
  Native missing-ID event uses omitted wire ID, not null (schema correctly rejects null).
  Test corrected accordingly. A missing creation timestamp with valid update is covered.
- Browser/DB proof: all four document contexts saved; H6/fence metadata retained. Native
  table/keyboard formatting persisted in Knowledge. Held persona stream opened exact file,
  duplicate/cold replay stayed Gallery, historic card click opened latest version by path.
  Read-only prototype source and code blocks reject typing even though CodeMirror's DOM
  contenteditable can remain true; Save disabled. No permission changes made to real users.
- Native API gaps recorded in toolbar plan: H1-H6 selector; no Mod+Shift+X/E/list chord.
- Founder flagged the transcript's Persona verification card: inherited Plan shell has an
  empty body/divider/toggle for reference-only cards. Added isolated compact file-link preview
  at http://localhost:3047/file-card; do not apply styling to main until reviewed.
- Fixture project/thread archived; test Knowledge path removed. Stream completed and zero
  fleet tasks verified. Cleanup initially tried removing its control row; the append-only
  guard refused and rolled back that transaction. Keep stream/control/submission audit and
  the queue hold on the archived thread; no guard bypass. Local checkpoints: 248ced412 (Gallery/named tabs); compact chat-card preview committed separately.
  No environments or sibling processes changed.

- Closing state: original project restored in browser; compact card preview left at
  :3047/file-card. No permanent Plan/Documents tab in live chat. Main chat-card chrome
  intentionally unchanged pending review of the new visual preview. User specifically
  confirmed feedback concerned the transcript card, not Gallery cards. All requested
  editor/Gallery work is implemented and verified; no push was performed.
