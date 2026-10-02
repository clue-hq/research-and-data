# Reasoning presentation POC — 2026-09-12

Founder now requires discussion and agreement on each polish item BEFORE main-feature
implementation. The four-item queue is reasoning presentation, Stop, Home/chat composer,
and account research card (visual only). Inspection of Stop found an existing durable
endpoint, controller method and transcript-level button; no change was made to any item.

Reasoning ruling: remove duplicate step-completion/checkmark narration; prefer provider
trace text in a minimisable AI Elements Reasoning disclosure with Shimmer. First show a
POC and agree on the design; do not integrate into the live chat yet.

Separate local POC: `.runtime/reasoning-preview/`, served at http://localhost:3045.
Uses existing frontend Reasoning, Shimmer and MessageResponse source via esbuild; copies
the built app CSS to retain Clue typography/tokens. Main application source, dependencies,
flags, databases and running servers are untouched. No model calls or customer traces.
Sample text is explicitly labelled illustrative. Options: A inline disclosure, B soft panel.
Controls: streaming/finished/stopped/no-trace, long trace, replay of a synthetic stream.

Browser checks: manual collapse stays closed while text streams; completed traces collapse
and can reopen; long content is bounded to 256px (894px content) with internal scroll and
no horizontal overflow; no-trace removes both sample disclosures; stopped retains one
collapsed trace per response without checkmarks. A is recommended for the existing chat.
The library's automatic re-open would prevent minimising a running stream; POC supplies
defaultOpen=false plus controlled open state to respect manual collapse without changing
the installed library. Streaming completion still uses its existing auto-close behavior.

Data discussion owed before integration: backend reasoning text is currently provider-
dependent, developer-only, ephemeral and not persisted. See ReasoningPart in turn_parts.py
and CLUE_CHAT_REASONING_TRACE_MODE in settings.py. Current duplicates are separate
reasoning and agent_activity part renderers in chat-message-part.tsx/chat-agent-activity.tsx.
No raw-trace availability or persistence decision has been made for production.

Commands: `node .runtime/reasoning-preview/build.mjs`; then
`node .runtime/reasoning-preview/serve.mjs`. Server binds loopback port 3045 only.
Tooling corrections: initial standalone build resolved two React versions (monorepo root
versus frontend); explicit frontend React/react-dom aliases fixed it. Sandbox refused the
loopback listener; approved escalation started the POC server. No dependency install.
Final state: local interactive preview ready; main-feature implementation awaits selection.

## Approved implementation — 2026-09-12

Founder selected inline disclosure and explicitly requested plain-text reasoning, plus
wrapping for long monospace/backtick values and Markdown answers (no chat horizontal
scrollbar). That approval advances this item from POC to frontend implementation only.
Stop/composer/research-card changes still await their separate discussions.

Implemented `chat-reasoning.tsx` + its CSS module and the pure
`chat-reasoning-presentation.ts` aggregator. One disclosure per assistant response,
stream-ordered trace text, normal Clue typography, literal punctuation, 256px vertical
scroll limit, manual collapse preserved across streaming/rounds, automatic close at
turn termination. No trace means only an active Thinking label, no empty/completed
receipt. Deleted the activity renderer, its obsolete CSS and activity-label helper.
Actual tools/tasks/gates/sources remain. Cancelled/failed messages retain an explicit
terminal receipt now that reasoning no longer carries one.

Markdown answers keep the existing renderer. Message children and Markdown containers
have bounded widths; inline and fenced code preserve monospace but wrap (`pre-wrap`,
`overflow-wrap:anywhere`) instead of creating horizontal scrolling. No clipping-based
fix or Markdown parser in the reasoning path. Backend flags, payload contract and
reasoning persistence remain unchanged (development-only, provider-dependent, ephemeral).
Canonical presentation doc updated in `apps/frontend/docs/architecture/ai-elements-and-reasoning.md`.

Verification:
- 53 targeted reasoning/transcript/streaming-Markdown tests passed; six retained tool
  presentation tests passed after removing the obsolete activity-only test.
- Design-system build, lint and production build passed. Lint retains only the two
  existing unused-function warnings in design-editor canvasOperations.ts.
- POC now imports the actual ChatTranscript/component CSS rather than a parallel mock.
  Synthetic samples include 1,600-character backticks (closed and unclosed), long URLs,
  Markdown headings/lists/quotes/tables, fenced JSON/escaped Markdown, spaces and tabs.
- At 320px panel width: panel clientWidth=scrollWidth=318; trace=283/283; code block
  =286/286; document=1086/1086. No overflowing block descendants. Code remains monospace;
  reasoning contains zero code/pre/link/strong elements. Stream start/completion and
  manual collapse/reopen, stopped receipt, no-trace terminal state all checked.
- Live Semarang chat at :3040 remained usable with zero horizontal document overflow
  and no legacy reasoning/activity labels. No new model/API mutation was submitted.
- Existing POC server :3045 was the only restarted process; all other workspace servers
  and database state were left alone. Updated preview remains available for review.

Tooling notes: direct tsx CLI was blocked by its local IPC pipe; `node --import tsx --test`
ran without that listener. One edit command initially used the wrong cwd and changed
nothing, then was rerun from repo root. Actual Next Image needs `process.env` defined in
standalone esbuild; the isolated preview defines an empty object (no real env exposure).
CUA reset renumbered the browser handle; re-listing tabs recovered it. Preview no longer
has the early missing-process error after rebuilding. Final build/lint logs are under
`.runtime/logs/reasoning-polish-*`.

## Process clarification and plan

After `81942b704` was committed/pushed, the founder approved the previews and
asked to proceed with an implementation plan. This clarifies that the preceding
preview approval was interpreted too broadly: the assistant had already integrated
before the requested plan discussion. Acknowledge that directly; do not portray the
landed work as merely proposed or automatically continue into backend changes.

The canonical AI Elements architecture document now contains a five-step plan with
landed/pending status. Remaining work: agreed real provider-backed conversation
acceptance, keyboard/reduced-motion checks, and explicit production trace availability
and retention decisions if desired. Current turn changes documentation only. No new
code, model call, flag change, database change or server restart.
