# Lane 2 MDXEditor prototype — 2026-09-13

- Founder authorized a working isolated prototype, not production migration. Created
  `prototypes/mdx-editor` with its own npm manifest/lock, Next app, generated copies of
  Clue tokens/fonts, sample documents, native toolbar, react-markdown Preview, local
  browser Save/Discard and full/440/360px panel controls. Serves 127.0.0.1:3047.
- Production app/dependencies/config/env/database untouched. Only prototype-owned server
  tool session was restarted after installing dependencies. Founder reiterated that no
  sibling workspace processes may be stopped; all other servers were left running.
- Founder live review removed the code-block language picker. Blocks are now plain
  monospace; existing fence metadata survives. Inline monospace remains available.
- Compatibility experiment: MDXEditor 4.2.5 with app Next 16.2.12/React 19.2.4 builds,
  but app Lexical 0.49 alongside MDX's 0.48 gave multiple Lexical instances and a browser
  HorizontalRuleNode constructor error. Removed only prototype experimental app-Lexical
  dependencies; native 0.48 dedupe resolves it. Main-app integration remains gated.
- Fixed observed prototype defects: toolbar's inner wrapper overflow at 360px; automatic
  URL linking causing false dirty state; import-error trimming marking source dirty;
  source drafts lost on readOnly transitions. Preserve current draft by explicit remount
  on permission changes; Preview/Edit and switching samples keep existing editors/history.
- Stable plugin/toolbar identities reviewed using React best-practices skill. Native
  commands/parsing/history/serialization retained; no custom formatting engine.
- Browser proof: formatting, links, table creation/editing, deep headings, inline/block
  monospace, source recovery, browser Save/reload, Discard, independent drafts, undo
  across Preview/Edit, read-only source input rejection and permission-transition draft
  retention. 360px panel contained; table alone can scroll. Separate 127.0.0.1 QA origin
  prevented edits to the user's localhost demo drafts. No final QA console warnings/errors.
- Tooling: sandbox npm network required escalation; an earlier npm metadata attempt was
  interrupted. Initial import-name TypeScript error corrected. One table-cell automation
  fill prepended text; verification used observed output, not the intended replacement.
  Initial rapid post-reload selection raced hydration; selected after editor loaded.
- Closing gates: prototype TypeScript/build pass; focused tests cover baseline/Save guards
  plus shared Lexical constructor identity. README records reproducible steps, verified
  behavior and remaining main-app compatibility/backend/keyboard acceptance. Lane 2
  Task 5 Step 1 remains unchecked; no production integration or remote publication claimed.
