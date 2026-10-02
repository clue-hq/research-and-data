# Rich text editing in the scene (ad) editor — design + implementation plan

**Date:** 2026-08-24 · **Branch:** `integration/frontend-design-part-iv-v8` · **Status:** founder-directed
(scope ruling from the 2026-08-24 debug-slow-runs conversation: rung **C is the destination, shipped
A→B→C in that order** — A kills the "I couldn't edit the text at all" pain, B/C stack without rework).
This supersedes, with this dated note, the AD4.C §1.9 / §7 deferral of double-click text editing
(`docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` §1.9+§7, and the execution plan's
AD4.C step-1 scope line).

## The ladder

- **A — content editing:** change what a text node *says* via a Content field in the ad text inspector.
- **B — canvas inline editing:** double-click a text node opens a real caret/selection session on the
  canvas (port of upstream `TextEditOverlay`), whole-node styling only.
- **C — true rich text:** select a range inside the session and bold/italic/underline/strike/recolor it,
  riding the engine's `TextSpan` machinery end-to-end, including the content-edit-vs-spans reconciliation.

## Ground truth (from the 2026-08-24 exploration; verified file+line in the session record)

**The engine needs no changes.** `TextSpan` = UTF-8 **byte** offsets into the *stored* `content`
(`start`/`end`, sorted, non-overlapping, char-boundary aligned) with optional `fill` (solid/token only),
`font_weight`, `underline`, `strikethrough`, `italic` (override semantics). Validation
(`span_validation_errors`, lumen-core `scene.rs:754`) runs at **layout**, not apply — an invalid span
applies clean and surfaces as `LUMV0906`; the node drops out of measurement. → the frontend must
pre-validate every span vector it sends.

**D4 (content-edit-clears-spans) is enforced engine-side at both write paths**, including the whole-kind
`update_node` path the editor uses (`operations.rs:620-631`: content changed + spans byte-identical →
cleared; re-authored *different* spans survive; undo restores). Corollary gotcha: to keep spans across a
content edit you must send a *changed* spans vector.

**The editor canvas already renders spans** (descriptor `text.spans` → `drawSpannedText` /
`buildSpannedParagraph` in `drawDescriptors.ts`; measurement records carry spans into `setMeasurements`
so the engine's `measure_key` digest matches; `scene-canvas-view.ts` fingerprints `t.spans`). The
raw↔normalized byte-offset math (`normalizeContentMapped` / `transformSegments` in `textTransform.ts`)
is the hand-written TS twin of the Rust helpers and is exactly what C needs.

**Write vehicle:** `updateTextNode(node, {content?, spans?})` (`operations.ts:395`) → `applyOps` →
editQueue (D10 CAS) → one server envelope → **one undo frame**. `modifyNodeEdit`'s
`TextEditPatchInput` has no `spans` channel and zero production callers — not used by this work.

**Gaps this plan fills:** no `content` in `InspectorPresentationState`/hydration; no multiline inspector
primitive; no `case "content"` in `sceneChangeToOperation`; no double-click handler on the scene stage;
no span-algebra module; no selection→byte-offset mapping; no span-authoring UI anywhere (upstream defers
it too).

## Standing constraints (all binding)

1. **AD4.R MVP state model:** the engine owns document values; inspector rows bind
   `value={state.x}` + dispatch-only commits; typed fields self-draft via `onCommitValue`
   (`fieldDisplay`/`fieldCommit`); commit on blur/Enter — never per keystroke (one keystroke = one
   document version otherwise).
2. **Presentation truth:** no invented chrome. Rung B ports upstream `TextEditOverlay` (named in the
   disparity inventory §3.10 as the upstream affordance the platform lacks). Rung C's toolbar lifts the
   existing `web-rich-text-toolbar` presentation pattern (the repo's one designed formatting-toolbar
   surface). Founder-visible: the scene toolbar reuses that visual language rather than a new design.
3. **G-H gating:** every new value control takes `inert = locked || inspectorDisabled`; the overlay must
   not *open* while `gestureDisabled`/`threadBusy`; an open session is not force-killed by a turn start
   (same posture as in-flight gestures — D10 CAS is the net).
4. **Locked nodes refuse** (write-side `scene-apply.ts:669` stays authoritative). Managed (auto-layout)
   nodes **do** allow text editing — content edits re-solve layout; ~~no freeze-on-grab needed for a
   text session (C-9 freeze stays a drag/resize concern)~~.
   **[CORRECTED 2026-08-24, adversarial review F5 — prose only, no behaviour changed]** The struck
   sentence was false about the mechanism. The text SESSION adds no freeze, but the double-click's
   first pointer-down runs `freezeLayoutForPress` like any press on a freezable node, so opening a
   caret on a layout-managed text node has already baked the document's layout to free placement —
   exactly as a plain selection click on that node does. That is ratified AD4.C-3 / ruling C-10
   behaviour and this lane deliberately left it alone; only the two docstrings that claimed the
   freeze "does NOT fire" (`adapter/scene-text-edit.ts`, `components/scene-artifact-canvas.tsx`) were
   rewritten to say what actually happens. See founder-visible item 8 for the open question.
5. **Testability:** the suite runs only `*.test.ts` — every decision lives in a pure `.ts` module
   (`adapter/` or `engine/scene/`), components stay thin.
6. **Wasm-backed proof:** the D4-through-wasm test (upstream `wasmOperations.test.ts:520-554`) gets a
   platform twin; artifact-gated suites self-skip without the vendored wasm.

## Design

### Rung A — inspector Content field

Data flow (all existing patterns; ~5 touch points):

1. `InspectorPresentationState` gains `content: string` (+ `DEFAULT_STATE` default `""`).
2. `hydrateSceneInspectorState` text block sets `state.content = text.content`.
3. New primitive `InspectorTextArea` in `inspector-primitives.tsx`: a `<textarea>` sibling of
   `InspectorInput`, reusing `fieldDisplay`/`fieldCommit` verbatim; commits on **blur and ⌘/Ctrl+Enter**;
   plain **Enter inserts a newline** (multiline content is real — this is the one deliberate divergence
   from `InspectorInput`'s Enter contract, disclosed here). Repeats both `disabled` guards (draft AND
   commit — the programmatic-blur hazard).
4. `AdTextInspector`: a "Text" row first in the `typography` section, `disabled={inert}`,
   `value={state.content}`, `onCommitValue` → `setValue("content", v)`.
5. `scene-apply.ts` `sceneChangeToOperation`: `case "content"` → `updateTextNode(node, {content: value})`
   (string values only; guarded on the text kind; locked already refused above the switch).

Empty string is a legal commit (clearing text is a real edit; the node survives). A content edit on a
spanned node clears its spans — engine D4, honest and undoable; rung C upgrades this (below).
`fieldCommit` suppresses no-op re-types against the live value. Refusals revert per AD4.R.

### Rung B — double-click inline editing (upstream port)

- **Entry:** `onDoubleClick` on the stage div, reusing the existing coordinate chain
  (`screenToWorkspace → sceneDescriptorPoint → descriptorToScene → controls.hitTest →
  representableHit`). Hit a text node → open session (+ select it). Hit a non-text node → upstream's
  drill-out via the already-built `topLevelAncestorId` (`sceneQueries.ts:150`, docstring names this
  consumer). Locked node or `gestureDisabled` → no session.
- **Surface:** `SceneTextEditOverlay` (port of upstream `TextEditOverlay.tsx`): a DOM `<textarea>`
  positioned over the node in descriptor space (geometry from the selection-chrome box model), styled
  to match font/size/weight/align/valign (upstream's paddingTop recompute), editing the **stored**
  content (text_transform applies only to painted text; the overlay shows raw content, upstream parity).
  Spans do not render inside the overlay (plain text; upstream parity, disclosed).
- **Session rules:** commit on blur or ⌘/Ctrl+Enter → one `updateTextNode` batch through `onOperations`
  (one undo frame); Escape cancels (no op; the canvas's window Escape listener is already inert for
  typing targets). While editing: the node's painted text is suppressed via a render-time descriptor
  override (the AD4.C preview mechanism), selection handles go dark, presses don't arm
  (`typingTarget` + an `editing` guard in `handlePointerDown`). No-op commit (unchanged content) sends
  nothing.
- **Decisions live in** `adapter/scene-text-edit.ts` (pure): `canOpenTextEdit(press/scene/flags)`,
  `textEditGeometry(chromeModel, descriptor)`, `textEditCommit(before, after) → Operation[] | null`.

### Rung C — range styling riding spans

**Selection surface decision.** Three candidates were weighed:
(1) **native textarea selection** inside the rung-B overlay — zero new hit-testing, selection comes
from `selectionStart/End`; not WYSIWYG mid-session (textarea is plain text);
(2) contentEditable overlay rendering segment `<span>`s — WYSIWYG-ish, but DOM↔byte mapping and
mutation control are a large new surface; (3) full CanvasKit caret/selection
(`getGlyphPositionAtCoordinate`/`getRectsForRange`) — most faithful, biggest build, and the engine
exposes no glyph geometry (frontend would retain its own Paragraphs).
**v1 ships (1)**; (2)/(3) stay the recorded upgrade path. Styling feedback is immediate on commit
(canvas repaints spans), and the toolbar shows live on/off/mixed state, so the honesty cost is small
against the build cost of (2)/(3).

- **Toolbar:** while a session is open, a floating toolbar above the overlay (visual language lifted
  from `web-rich-text-toolbar`): **B / I / U / S** toggles + a text-color control (solid hex + brand
  tokens via the existing color-control pattern). Buttons reflect tri-state (`on`/`off`/`mixed`) for
  the current selection; collapsed selection (caret only) targets the **whole node** row? No — v1:
  collapsed selection disables the span toggles (honest; whole-node styling already lives in the
  inspector). Applying a toggle with a live range: computes the new spans vector, commits **immediately
  as its own operation batch** (one undo frame per formatting action), keeps the session and selection
  open.
- **Offset mapping:** `selectionStart/End` are UTF-16 code units → converted to UTF-8 byte offsets
  (pure helpers next to `textTransform.ts`'s byte math). All span math is in **stored-content byte
  space**; no normalized-space leakage (the painter does its own relocation).
- **Span algebra:** new pure module `engine/scene/textSpans.ts`:
  - `formatStateForRange(content, spans, [s,e)) → {bold, italic, underline, strike, fill}` tri-states;
  - `applyStyleToRange(content, spans, [s,e), patch) → TextSpan[]` — split/merge, drop no-op spans,
    always emitting a **sorted, non-overlapping, char-boundary-aligned** vector that satisfies
    `span_validation_errors` (client-side pre-validation mirrors the five rules; a would-be-invalid
    vector is a bug, guarded by tests, never sent);
  - `reconcileSpansAcrossEdit(before, after, edit, spans) → TextSpan[]` — the reconciliation (next).
- **Content-edit-vs-spans reconciliation (the D4 surface):**
  - *In-session typing:* the overlay tracks each contiguous replacement (`beforeinput` → old range +
    inserted text) and shifts/trims spans incrementally — styling survives typing, like any real editor.
  - *Commit:* sends `{content, spans}` together; if offsets moved the vector differs, so D4 lets both
    apply. Edge: content changed but the maintained vector is byte-identical (edits entirely after all
    spans) — the engine would read identical-spans-as-stale and clear, so the session **re-authors
    consciously**: identical-but-still-valid vectors are sent as-is only when content is unchanged;
    when content changed we always send the maintained vector, and if it happens to be byte-identical
    we accept the engine's documented clear *unless* the vector still validates against the new
    content, in which case a no-op split-and-merge normalization is applied to make it differ. (Pure,
    tested; keeps the engine's honesty rule intact without corrupting offsets.)
    **[AMENDED 2026-08-24, review F1+F2 — two defects in that re-authoring, both fixed]** (a) the
    "is it byte-identical?" question must be asked of the **raw stored vector**, which is what the
    engine compares (`after.spans == before.spans`); asking it of a *normalized* copy made the split
    self-defeating, because a second suffix edit regenerated exactly the split the document already
    held and the engine cleared every span — silent styling loss on the second edit of any node.
    (b) when nothing can be split — every span one character wide, e.g. a coloured "!" — the vector
    used to go out unchanged and die; it now **restates a channel** the span does not carry at the
    node's own value (`underline`/`strikethrough`/`italic`, or the weight for a node with no
    `style_token`), which paints identically and differs in bytes. The clear is accepted only for the
    one shape that can express neither: a single-character span already stating every channel.
  - *Fallback:* an untracked mutation (autofill/IME edge) → prefix/suffix diff remap; still ambiguous →
    clear (engine-honest default), never guess.
  - *Inspector content commits (rung A path) upgrade:* `case "content"` remaps existing spans with the
    same prefix/suffix diff instead of letting them all clear — spans fully inside the unchanged
    prefix/suffix survive; spans touching the changed middle are trimmed/dropped.
- **Whole-node vs span interplay:** inspector node-level controls keep writing node fields (spans
  override per-range; engine semantics). No new inspector rows for spans in v1.

### Error handling (all rungs)

- Engine refusal (`!accepted`) → existing `setError` slot; overlay commit failure keeps the session
  open with the typed text (nothing lost).
- D10 CAS conflict mid-session: the reload replaces the scene; the session validates its node still
  exists on reconcile — node gone → session closes, draft discarded with the standard D10 note
  (matches AD4.R's mid-typing-draft-survives posture where the node survives).
- Span vectors are pre-validated; a validation failure in `textSpans.ts` is thrown in dev/test, and in
  production falls back to not sending the spans channel.

### Testing

- Pure modules carry the weight: `inspector` state/hydrate deltas, `scene-apply` content case,
  `scene-text-edit.ts` decisions, `textSpans.ts` algebra (property-style edge tables: unicode
  (emoji/combining), boundaries, adjacent spans, merge/split, all five validity rules), offset mapping
  (UTF-16↔UTF-8), reconciliation (typing scripts, prefix/suffix fallback, the byte-identical edge).
- Wasm-artifact tests: platform twin of upstream's D4-through-wasm test; a spans round-trip
  (apply `{content, spans}` → `sceneJson` carries them → undo restores).
- Existing-test discipline: rewrite-never-delete for any pinned ruling this supersedes (the §1.9
  no-double-click pins, if any assert it).
- Gates per rung: frontend suite + `npm run design-system:build && npm run lint && npm run build`;
  root `make check` untouched (frontend-only work); browser proof on the seeded ad against the live
  stack at each rung's close.

## Founder-visible items (defaults chosen; all reversible)

1. `InspectorTextArea` commits on ⌘/Ctrl+Enter (Enter = newline) — diverges from `InspectorInput`.
2. Scene formatting toolbar reuses the web toolbar's visual language (no new design commissioned).
3. C's v1 selection surface is the overlay textarea (not WYSIWYG mid-session); upgrade path recorded.
4. Collapsed-caret span toggles are disabled (whole-node styling stays in the inspector).
5. Each formatting action = its own undo frame.
6. Inspector content edits remap spans via prefix/suffix diff once C lands (before that, engine D4
   clears them).
7. **[added 2026-08-24, review F4] A refused overlay commit KEEPS the session and the typed text** —
   the session stays open, the caret comes back, and the human can retry or Escape. This deliberately
   differs from the inspector's revert-on-refusal (AD4.R): a one-line field's refused value is one
   keystroke from being re-entered, while a multi-line draft someone just wrote is unrecoverable once
   the session closes. Same refusal, different cost. (A refused FORMATTING commit still reverts — the
   session's working spans go back to the pre-action vector, because only the styling was refused and
   nothing typed is at stake.)
8. **[added 2026-08-24, review F5] Option — defer the C-9 freeze to the drag threshold**, so pure
   clicks and double-clicks stop freezing the document's auto-layout at all. Today the freeze fires on
   the press (see standing constraint 4's correction), which means opening a caret on a managed text
   node bakes the layout as a side effect of wanting to fix a typo. Changing it would change ratified
   AD4.C-3 behaviour for every press, not just text ones — **needs a founder ruling; nothing was
   changed here.**
9. **[added 2026-08-24, review round 2 / G1] A concurrent write and an open session settle PER
   CHANNEL.** The session tracks "the human typed" and "the human formatted" separately. A session
   whose human only clicked Bold now ADOPTS an agent's concurrent rewrite of the text (its working
   spans are remapped onto the new string by prefix/suffix diff) and commits only the styling; a
   session whose human typed keeps its draft as before. The visible consequence: styling applied just
   before an agent turn lands can end up over *different words* than it was applied to, because the
   remap is conservative and never guesses what changed in the middle. The alternative — refusing the
   formatting commit outright — was not chosen: it would lose the human's action to a race they could
   not see.

## Residuals (recorded, not fixed — round 2, 2026-08-24)

- **The D4 restatement fallback is exhaustible, and reachably so.** When a content edit's maintained
  span vector would reach the engine byte-identical to the stored one, `spansVectorForContentEdit`
  re-authors it — first by splitting a span, and (F2) for an unsplittable one by restating a channel
  at the node's own value. That second fallback has at most FOUR channels per span, so four
  consecutive suffix edits on a single-character span burn underline, strikethrough, italic and the
  weight, and the fifth collides again and the engine clears the styling. The F2 docstring called that
  case merely "constructible"; it is an ordinary sequence of keystrokes on a coloured "!". The clear
  is still honest and undo still restores it. (Corrected in `textSpans.ts`.)
- **A restatement is durable, not a marker.** It writes a real span override at the node's value, so
  that run STOPS following later changes to the node's own base: restating italic or the weight pins
  real pixels, and restating a decoration pins what the union-painted toolbar reads — a later
  node-level change can leave the toolbar and the paint disagreeing over that run.
- **A refused commit can be silent.** `use-scene-manual-edits.ts`'s not-armed path returns false with
  no message, and D9 read-only relies on the G-D banner rather than a per-write refusal. A session
  that refuses to commit therefore holds the caret with no stated reason; Escape exits but costs the
  draft. Fixing it needs a decision about a shared refusal message on the write path — **not this
  lane's to make**, recorded so the next owner of that path has it.

## Implementation plan (each task: TDD, focused tests, then the frontend gate; local commit per task)

- **T1 (A):** state + hydrate + `case "content"` + `InspectorTextArea` + the inspector row.
  Tests: hydrate/apply/primitive-logic. Commit `feat(design-editor): text content editing in the ad inspector`.
- **T2 (B):** `scene-text-edit.ts` decisions + `SceneTextEditOverlay` + stage `onDoubleClick` + paint
  suppression + chrome/gesture interlocks + §1.9/§7 supersession notes in the two contract docs.
  Commit `feat(design-editor): double-click inline text editing on the ad canvas`.
- **T3 (C-core):** `textSpans.ts` (offsets, algebra, validation, reconciliation) — pure, no UI.
  Commit `feat(design-editor): span algebra + reconciliation for scene rich text`.
- **T4 (C-UI):** toolbar + selection wiring + immediate span commits + inspector remap upgrade +
  wasm D4/spans round-trip tests.
  Commit `feat(design-editor): range styling toolbar riding engine spans`.
- **T5:** browser acceptance walk on the seeded ad (all three rungs), memory close-out note.

Rung boundaries are shippable checkpoints: A alone is releasable; B without C likewise.
