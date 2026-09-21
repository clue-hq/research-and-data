# Fresh native website acceptance

- Continue the existing capture/reproduction/account-skills goal; do not mark it
  complete from auth recovery or a successful model/tool run. Latest founder scope
  permits live testing only in Conduit Fresh on 3020. Old four workspaces remain
  suspended; prior cross-brand frozen-source evidence is not fresh native acceptance.
- Saved native test resumed after Google sign-in repair. Current run uses the approved
  fresh kit, captured homepage/two products/customer index/two customer stories,
  and the actual Clue design agent. Prior page versions remain separate.
- Founder correctly noted that the submitted test prompt is unusually detailed.
  Let that run finish without interruption. Classify it as a directed workflow test,
  not proof that ordinary users can get the same quality from simple instructions.
  Next ordinary-input test should use a short request such as "Create a Conduit
  landing page for Hyatt" with the existing agent/skill defaults, not a pasted
  quality checklist or hidden per-brand instructions.
- Early trace: actual reads of account argument, readiness, composition, media,
  conversion and repair guidance. Project Hyatt query returned no account. This can
  prove an honest task-relevant proposal, not researched account personalization.
  Do not initiate discovery/research or invent target evidence to pass that gate.
- Acceptance still requires rendered desktop/mobile source type/layout/media,
  authentic target logo, relevant copy, real CTA destinations, supported interaction
  states and honest missing-evidence reporting. CSS truncation is an inspection
  boundary; use existing pagination/targeted tools rather than rewriting full source.
- Fresh capture succeeded and the kit is approved. Overall onboarding aggregate
  still records the earlier alias failure although 15 steps completed; keep these
  separate in reporting.

## Directed run completed; parent review

- Run completed in 8m51s, saved the new native page v1, outcome
  completed_with_warnings. Correct fresh kit; six captured bands plus composed
  campaign header/footer. Trace records 119 tool calls, 21 section searches,
  four logo fetches, one rendered review and 14 successful skill/reference reads
  (13 distinct paths). No standalone page or manually seeded brand library.
- Hyatt provider asset was correctly rejected as the loyalty-program logo.
  Corporate arched wordmark from the official investor site is in the final
  header, verified visually. Parent inspected native desktop/mobile. Five demo
  links all point to the official absolute destination; legal links are absolute.
  Mobile has no horizontal overflow in the observed native preview.
- Parent clicked the procedure control: it did not change the selected state or
  exposed image. This is a real unresolved interaction defect, not a full fidelity
  pass. Mobile Inbox UI is hidden, leaving a tall background wash; source-parity
  versus capture/renderer cause still needs investigation.
- Corrected model self-review: security seals are NOT missing on mobile. Scrolling
  the live native preview loads all three (170px decoded/rendered). Offscreen
  lazy images in the compressed preview are insufficient missing-media evidence.
- User's current Home draft was left intact. A separate inspection tab displays
  the completed artifact. No new generation, research or edits to the finished
  draft were submitted during this acceptance pass.

## Logo search defect found during the run

- Recorded `search_assets(q="Hyatt corporate logo", kind="logo")` returned zero
  despite fetched document assets. Fetch stores SVG/PNG under vector/raster_image;
  the kind alias only recognized raw logo records. Exact-ID search worked, proving
  inventory presence, and dropping the kind filter exposed the assets.
- Regression reproduced empty results before repair. Search now reuses the existing
  fetched-logo provenance predicate for image records, preserving raw image kinds
  and refusing label-only/logo-tagged documents. Tests cover document, kit and
  library origins, explicit IDs, raw kinds and misleading labels.
- Targeted asset search/rendition checks: 58 passed. Full runtime suite finished:
  2722 passed, seven skipped and five failed. Four failed because the sandbox
  prevented Chromium starting; the four passed when rerun with local browser
  permissions. The remaining failure is the existing exact-wording assertion in
  `test_the_tool_docstrings_carry_the_amendment_too`; its `search_cloned_sections`
  target is identical to HEAD and outside this logo-filter repair. Full suite is
  therefore not green. Diff whitespace check passed.
- Workers are not reloaded while the user may have other work running; the completed
  directed run used the previous code and is not live verification of this repair.

## Next fidelity follow-up

- Read-only review found preview capture waits for styles but does not reliably
  scroll or decode offscreen lazy media. Desktop full-page capture precedes the
  scroll walk; mobile/reduced-motion captures do not walk. This explains why a
  screenshot alone cannot establish missing assets. Native scrolling was decisive.
- Implement a shared bounded media-readiness check for preview and clone-review
  paths, preserving scroll position and reporting unresolved media separately.
  Verify with delayed lazy media and genuine failed-media fixtures. Do not repair
  the actual three security assets, which load correctly in the native preview.
- Preserve this directed output as the review baseline. Run ordinary-input
  acceptance separately; do not count this heavily guided run as that gate.

## Ordinary-input attempt and user steering

- Submitted exactly one new native request: "Create a Conduit landing page for
  Hyatt." Project prj_be16c8d37cf055d9a5b8aa15a183d333, thread
  thr_bc7c11b23f315f91a226178426310192. Head opened generation without a second
  confirmation prompt. Run run_fd655b9b17db5f0fa65fd10d395c67b4 selected the correct
  fresh kit, read 13 skill/reference paths, inspected source sections and logos.
- Durable result then became failed with "cancelled by request" at 15:36:50 local.
  Only asset upserts had completed; no authored page layout. This is not generation
  quality evidence. The parent did not request the cancellation and did not retry.
- User explicitly said no more repeated prompts: wait and watch the existing run.
  Do not start another generation automatically after this cancellation. Existing
  directed output remains intact; no research or publishing was launched.
- Responsive root cause verified separately: frozen desktop snapshot's mobile
  product branch contains only the background image. At 375px the real source
  mounts a complete chat demo into that branch. This content was never present in
  our desktop capture; CSS repair alone cannot recover it. Source procedure buttons
  also switch aria-pressed and imagery, unlike the saved static fragment.
- A bounded read-only audit found responsive snapshot custody currently keys only
  on (job, page URL); a naive second viewport would overwrite desktop evidence.
  Requires explicit viewport/state identity and variant selection, not seeded markup.
- Media-readiness subagent patch is uncommitted and not loaded into services.
  Six new local browser regressions pass; wider focused verification pending.
  User steering stops expansion and new live submissions while retaining this work.

## Capture-readiness implementation review

- Continued only local verification after the user stopped further prompt submissions.
  No generation, ingestion, research, service reload, or remote push in this slice.
- Shared screenshot helper now walks lazy images under a bounded deadline, waits
  for decode, restores scroll, and reports unresolved media. Full-page agent
  previews and clone-review desktop/mobile/reduced-motion passes use it.
- Moved readiness enforcement into the shared critique, requiring an explicit ready
  media report from every measurement-producing desktop/mobile pass. Missing or
  malformed reports keep findings advisory; reduced-motion height comparison also
  requires ready images on both sides. Unready previews cannot satisfy the cache.
- Parent reproduced eight false-settled cases and a real-browser reduced-motion
  false-settled case before fixing them. Reviewed the delegated helper and found
  clipped inactive images could stall captures: reproduced two browser failures,
  then excluded fully clipped content while retaining below-fold visible images.
- 202 initial focused checks passed. Final browser matrix: eight passed, including
  two clipped-image cases. Full runtime suite in progress; do not claim its result
  yet. Full API suite not run against the live DB.
- Verification setup mistakes: first focused command named a nonexistent review
  test file (exit 4, no tests ran); corrected test_web_review_gate.py passes. New
  helper/browser-test Ruff clean, compileall and diff whitespace clean; existing
  touched-file lint debt remains.
- Limits: this fixes screenshot evidence, not source ingestion or uncaptured
  mobile React branches. Video/CSS-background readiness and viewport-only modal
  snapshots are not certified by this helper. Responsive capture identity/custody
  and source interaction capture remain required follow-ups. No seeded repairs.
- Final focused gates: 101 passed (API critique + runtime durable-write behavior).
  Parent mutation control disabled warmup only inside a test process: the real
  browser rendered a white pixel where the delayed image should be red, and the
  screenshot regression failed as intended. Production files were unchanged.
- Full runtime command uses the existing repo venv/PYTHONPATH, local Chromium
  escalation and /private/tmp/clue-media-runtime-full-20260921.log. It collected
  2,737 tests and is progressing through existing slow retokenize tests.
- Checkpoint handoff: full runtime execution handle 36344 is confirmed live;
  last progress passed the slow typography section (47%+). Re-poll the same
  handle/log, do not start a duplicate suite. Local commit is still pending its
  result. HEAD remains 8d3842b7; all current changes are scoped to this capture fix
  and its operational note. No API/frontend/worker restart and no new live prompt.

## Capture-readiness verification closed

- Full runtime handle 36344 finished exit 1: 2,729 passed, seven skipped, one
  pre-existing failure: test_web_recreate_and_repair.py::
  test_the_tool_docstrings_carry_the_amendment_too. It asserts an exact phrase in
  search_cloned_sections; AST comparison confirms that docstring is identical to
  HEAD before this patch. No test was weakened or production wording changed to
  appease it. Full suite is not green.
- Final local browser tests: eight passed. Final API-critique/runtime-review gates:
  101 passed. Preview/substrate checks also passed in the earlier focused run.
  New helper and browser test Ruff, compileall and git diff --check passed.
- Ready for scoped local commit; no running verification handle remains. Services
  still use the prior loaded code until a separately scheduled idle reload.
- Next source-fidelity gap verified in current code: SiteSnapshot and durable DAL
  both represent a single state per (job,page URL). A second responsive capture
  must not overwrite the desktop original. Capture-state custody and selection
  need an explicit implementation before recapture; no native rerun is authorized
  by the user's latest wait-and-watch instruction.

## Responsive capture design audit

- Capture readiness committed locally as b5b4837f; no runtime reload or push.
- Rechecked the actual ingestion entrypoint: it already forces rendered capture
  universally. Do not "fix" this by altering static-tier quality escalation.
- Additional state identity crosses capture, custody, section provenance and
  source-flow reads. A same-URL snapshot list append would overwrite desktop;
  a DOM path without its immutable state reference could read the wrong source.
- Prepared proposed architecture in
  docs/superpowers/specs/2026-09-21-responsive-source-capture-design.md. It retains
  page identity and uses immutable state manifests in the existing design storage
  seam; no migration or new live capture was executed. Includes bounded acquisition,
  conservative source-branch reuse, exact state-aware reads and acceptance gates.
- Brainstorming architectural review gate applies to this newly specified change: a
  written-spec review is pending before implementation planning/product changes.
  Existing goal remains active. This is the first pending-review turn, not a
  repeated blocked condition. No new native prompts or automatic retries.

## Isolated capture-custody verification

- Honored the user's wait-and-watch instruction: no new prompt, ingestion,
  research, runtime restart, or live-data mutation. A read-only run lookup again
  confirmed the ordinary-prompt attempt is terminal with cancellation recorded;
  the chat's earlier generating message is stale, not a live-process signal.
- Completed independent verification while the responsive architecture review
  remains pending. Created a unique disposable local database, migrated from empty
  to the current head, and ran four API suites: clone-review registry, fragment
  isolation preview, ingestion site snapshots, and source-flow registry.
- All 41 tests passed (pytest exit 0). This covers durable reference provenance,
  snapshot/media/motion custody, workspace isolation, immutable preview attachment,
  explicit missing-reference handling and source-flow reads. It does not establish
  responsive source reproduction or live visual quality.
- Provider credentials were blanked only in the child environment; Python external
  connections were denied. Storage, engine cache and agent scratch paths were
  disposable. The test database was removed after completion; no live database
  was migrated and no product files or environment files changed.
- Setup failure: the first runner redacted every setting containing TOKEN, which
  also blanked numeric TTL/budget settings. Corrected that temporary runner to match
  credential names precisely. Its first database was cleaned up before retrying.
- Evidence: /private/tmp/clue-capture-db-check-joos4qg6/{migrate.log,tests.log,result.json}.
  This is additional verification of committed changes, not permission to execute
  the pending responsive-capture proposal. Goal remains incomplete; no push.
