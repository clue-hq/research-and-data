# Lane 2 Task 5 — shared Markdown editor and Knowledge migration

- Founder approved step 3 of the agreed sequence (Plan Tab plan Task 5) after Task 4.
  Semarang `visual-polish`; the lane index/plan remain authoritative. Plan/Gallery UI
  (Task 6 onward) is separate. No environment changes or sibling process stops.
- Added shared MarkdownArticle (react-markdown/remark-gfm) and a client-only MDXEditor
  boundary using the approved prototype's native controls and Clue tokens. Removed
  Knowledge's bespoke CodeMirror component/hook/styles. Code fences keep metadata
  but expose only monospace editing, with no language picker or line numbers.
- Aligned direct Lexical packages to MDXEditor 4.2.5's 0.48.0 tree without overrides.
  The existing direct consumer is the design text runtime, not the Slate composer.
  Added a constructor-identity test across MDXEditor/plugins/design imports. Added
  local @fontsource/dm-mono/300.css after the browser showed the code token falling
  back to Arial. No vendor code or generated vendor-class selectors changed.
- Feature sessions retain raw saved bytes, draft, original base revision and new save
  IDs by workspace + path. Initial normalization/undo does not create a false draft.
  Preview/Edit stays mounted; Discard/clean external replacement advances resetKey;
  dirty refreshes preserve the original base. Source errors retain source and disable
  Save until valid Rich text. Permission transitions remount from retained source;
  busy saves use inert so history survives. Page uses session project.write permission.
- Verification: 2,254 frontend tests passed (9 new lifecycle/dependency tests), token
  build passed, lint passed with only 2 pre-existing canvasOperations unused-function
  warnings, production build passed. React best-practices checklist reviewed. Runtime
  audit advisories all involve unchanged packages/versions; no broad upgrades attempted.
- Browser 3040: existing overview opens clean; typing/undo restores clean; Preview/Edit
  retains history. Two disposable Semarang-only Knowledge paths exercised table/list/
  quote/code imports, real v2/v3 saves, reload, undo after save, stale second-tab conflict,
  per-path draft retention, unsupported source recovery and Discard. At a temporary
  360 px component boundary rich editor/source/preview all had scrollWidth=clientWidth.
  Temporary width CSS and the 2 test document paths were removed; immutable fixture
  artifacts retained. Original company/product Knowledge was never saved or altered.
- Failures handled: initial lint rejected reading a ref during render (replaced with
  state); a relative-path CSS edit was retried from the correct cwd; first browser
  navigation timed out but its tab loaded successfully. Direct browser API navigation
  is blocked by the browser client. A read-only DB query found the current local DB
  lacks brand_knowledge_document.project_id (old runtime schema); fixtures used the
  existing schema. No migration/restart done. Lane 1 backend/schema rollout remains
  required before the future project-document live acceptance walk.
- Source-mode validation, font load and CSS specificity were verified in the main
  application, not inferred from the prototype. Listener PIDs 62085 (3040) and 62879
  (3047) stayed unchanged. Evidence: .context/lane2-editor-* (untracked).
- Closing checkpoint: implementation and scoped acceptance complete; local commit
  only, no push. Unsaved drafts remain in-page; only explicitly saved revisions are
  durable across reload, and the existing unload warning protects pending drafts.
