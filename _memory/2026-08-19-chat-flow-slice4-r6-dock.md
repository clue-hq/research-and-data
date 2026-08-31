# 2026-08-19 — Chat-flow editor integration, Slice 4: R6 live (dock choreography)

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md` §4 Slice 4.
Follows slices 1–3 (`f7540b63`, `f6d63cdc`, `3957166a`). Process: SDD, Opus implemented,
controller reviewed inline (no reviewer subagent) + re-ran gates.

## What shipped (commit `3ba169be`)

- **The chat screen's Edit now docks the REAL `WebInspector`** over the conversation
  transcript — the exact artifact-route prop set (`editor-surface.tsx:110-135`), keyed
  per selected node (never the document version — the founder-observed remount defect's
  comment discipline carried over), with the same selection fallback compose adapted to
  this mount's shell controller.
- **Dismiss-on-send:** in the composer `onSubmit`, `chatDockDismissedBySubmission(
  accepted.status)` → `shell.setEditing(false)`. Only `accepted` dismisses; `failed` /
  `not_submitted` leave the user mid-edit. `ProjectComposer` untouched; the composer was
  never inside `.chatBody`, so composer-stays held structurally (asserted in browser).
- **New pure-decisions module** `features/chat-shell/model/chat-dock.ts` (+ 5 tests,
  TDD): `chatDockOpen` (the old `editorVisible` verbatim), `chatDockContent`
  (web-inspector / ad-inspector / conversation), `chatDockDismissedBySubmission`
  (typed over `ChatSubmissionResult["status"]`, type-only import so the union can't
  drift). ChatSurface consumes these — no second copy of the rule.
- Dock guard deliberately stays `editorVisible && kind === "web"` (ledgered ruling) —
  NOT narrowed to `webEditingActive`, else a document-less web tab would empty
  `.chatBody`. Un-hydrated inspector + fail-closed writes is the correct posture there.
- Ad dock stays placeholder (ad-editor plan's scope).

## Verification

- Gates (implementer + controller independently): **762/762** (757 + 5 new), lint,
  production build.
- **R6 acceptance choreography browser-proven end to end** (Playwright, chat screen
  `/projects/prj_79aa…/chats/thr_4ef1f65…`): real transcript+composer → card → live
  canvas → Edit → transcript replaced by the REAL inspector (real layer tree
  Hero/Headline/Subheadline/CTA/Features/Feature grid, theme `#00F59B`; conversation
  aria region absent; composer flush at bottom, sibling of `.chatBody`) → Subheadline
  select (real hydrated values) → Alignment write engine-verified v92→93 → EMPTY submit
  does NOT dismiss (Send disabled + Enter no-op proven) → real send "noted, thanks —
  continue" → dock dismissed, conversation returned, message in transcript, agent
  queued a turn → Edit reopens the dock → Undo restored `sub.classes` byte-identical →
  artifact route regression-smoked. Screenshots `.playwright-mcp/slice4-0{1,3-9}*.png`.
- Note: the send test posted one real message to the seeded dev thread (plan-sanctioned;
  the agent queued a turn on it).

## Deferred minors (ledgered)

- `chat-dock.ts`'s type-only cross-feature import (first such edge from
  `chat-shell/model/`); `setEditing(false)` on every accepted send (one extra render);
  untracked `.artifacts/ws_…/` design-API runtime byproduct in the repo root → add a
  `.gitignore` entry at slice 6 close-out.
- R6's known cost stands (recorded in the plan): a running turn's gate/Stop banner is
  invisible while the dock is open — founder owns revisiting.

## Next

Slice 5 — URL write-back (`?surface=/?edit=/?selection=` round-trip, parse
`?surface=chat` deliberately). Then slice 6 close-out (R6 composer-stays clarification
into the Phase-C plan doc, contract notes, full gates + make check, walkthrough script,
`.gitignore` entry).
