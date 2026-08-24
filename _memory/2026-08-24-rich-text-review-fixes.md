# 2026-08-24 — rich-text (scene editor) adversarial-review fix wave

Branch `integration/frontend-design-part-iv-v8`. Base `098f243c` (frontend suite 2203 pass / 0 fail /
0 skipped) → one commit on top. Plan: `docs/superpowers/plans/2026-08-24-rich-text-editing.md`
(amended in the same commit).

## What was fixed (F1–F7, all TDD: red test first)

- **F1 (P1, silent styling loss).** `spansVectorForContentEdit` compared the candidate against the
  NORMALIZED stored vector; the engine compares RAW (`operations.rs:620-631`). Because the split is
  deterministic, a SECOND suffix edit regenerated the stored split → raw-equal → engine cleared every
  span. Now compares raw (`stableKey(node.spans ?? [])`), and the split chooser skips a candidate that
  collides with the stored key. Signature collapsed to `(node: TextNode, content, nextSpans)` — the
  stored vector and "did content change?" are both derived from the node, so the two can no longer
  disagree. Pinned by a chained two-commit case against the REAL wasm
  (`wasmTextSpans.artifact.test.ts`), a chained pure case, and an inspector-path case.
- **F2 (P3-1, unsplittable vectors).** No interior char boundary anywhere (every span one character —
  a coloured "!") → the vector used to go out unchanged and die. Second fallback added: RESTATE a
  channel the span lacks at the node's own value (`underline` → `strikethrough` → `italic` → weight,
  the weight ONLY when the node has no `style_token`, because `resolvedTextFields` resolves a token's
  weight over the literal). Renders identically, raw-differs. The clear stands only for a
  single-character span already stating every channel (constructible; pinned as such).
- **F3 (P2, idle session reverts a concurrent write).** `TextEditSession` gained `dirty` (set by every
  typing transition and by `applyStyle`; never by the model). Clean session RE-SEEDS from the live
  model (`textEditSessionReseed`) and writes nothing (`textEditSessionOperations`). Dirty session keeps
  its draft across a model change — unchanged posture.
- **F4 (P2/P3-4, refusal discarded typed text).** `commitTextEdit` now writes BEFORE closing and closes
  only when the write landed or there was nothing to write (`textEditSessionEnds`); `settle` re-arms
  its latch and takes the caret back on refusal. A refused formatting commit reverts the working spans
  (`textEditSessionAfterStyleCommit`). Keep-the-draft deliberately differs from the inspector's
  revert-on-refusal (AD4.R) — recorded as founder-visible item 7.
- **F5 (P2, false C-9 prose).** The freeze DOES fire — on the double-click's first pointer-down, via
  `freezeLayoutForPress`, like any press on a freezable node. Behaviour untouched; both docstrings and
  the plan's standing constraint 4 rewritten (dated correction, old text struck not deleted).
  Founder-visible item 8 records the "defer the freeze to the drag threshold" option as needing a
  ruling.
- **F6 (P3-2).** `scene-apply.ts` `case "content"` now runs the same `spanValidationIssues` pre-send
  guard the session path calls load-bearing (throw in dev/test, drop the spans channel in production).
- **F7 (P3-3 + P3-5).** The "⌘Z takes them back one at a time" comment was false inside a session
  (document undo skips typing targets) — corrected. P3-5 (a no-op content commit could mint a version
  carrying normalized spans; unreachable via `fieldCommit`) recorded as a code comment, not fixed.

## Gates

`npm test` 2225 pass / 0 fail / 0 skipped (2203 + 22; the wasm artifact suites RUN, 6 cases).
`npm run design-system:build && npm run lint && npm run build` — 0 errors, the 2 known
`canvasOperations.ts` unused-var warnings only.

## Round 2 (2026-08-24) — scoped re-review of `75a25835`

Base attested: HEAD `75a25835`, frontend suite 2225 pass / 0 fail / 0 skipped. One commit on top.
All three code fixes TDD (red test first, verified failing).

- **G1 (P2, the one that mattered).** F3's single `dirty` flag served TWO channels, and `applyStyle`
  set it — so a session whose human only clicked Bold stopped re-seeding AND claimed the content
  channel, and its blur committed the stale opening snapshot as a content write over a concurrent
  agent write. `TextEditSession.dirty` → `contentDirty` + `spansDirty`:
  - a text mutation (tracked / untracked / arbitrated) sets `contentDirty` only — the maintained spans
    ride along with a content commit regardless, so typing has no reason to claim the spans channel;
  - a formatting action sets `spansDirty` only, through the new pure `textEditSessionAfterStyle`
    (previously an inline `dirty: true` object literal in the overlay — moved so the rule has a test);
  - `textEditSessionReseed` is per-channel: `contentDirty` keeps the draft (unchanged posture);
    `spansDirty` alone ADOPTS the live content and remaps the working vector onto it via
    `remapSpansByDiff`, while refusing to take the document's spans back; neither dirty follows both;
  - `textEditSessionOperations` sends the session's content only when `contentDirty`, otherwise the
    node's LIVE content — so a spans-only commit does not trip engine D4 and cannot revert text.
- **G2 (P3).** A re-seed rewrote the textarea value while `selection` state and the DOM selection
  still pointed at the old offsets. New pure `textEditSessionReseedSelection` (select-all on an
  adopted content change, same object otherwise), plus a `useLayoutEffect` keyed on the adopted
  content that pushes the range at the DOM without touching focus.
- **G3 (P3).** The F2 weight-restatement guard read `!node.style_token` only. `resolve_text_style`
  (`brand.rs:3928`) also treats a token-ref `font_family` (`looks_like_token_ref`, `:6154` — `$…` or
  `token(…)` after trimming) as a style-token source, so restating the literal weight there is a real
  change at export. Guard is now `!node.style_token && !namesTokenRef(node.font_family)`; both shapes
  plus a leading-space one are pinned, and a literal family is pinned to still restate.
- **G4 (P3s, prose only, no code behaviour).** The F2 docstring's "constructible" framing was
  over-optimistic — the restatement fallback is exhaustible in four ordinary suffix edits, and a
  restatement is durable (that run stops following later node-base changes). Both, plus the silent
  refusal path (`use-scene-manual-edits.ts` not-armed returns false with no message; D9 read-only
  leans on the G-D banner), are now in the plan doc's new **Residuals** section. The G1 per-channel
  settlement is founder-visible item 9.

### Tests REWRITTEN (strict supersets, none weakened)

All in `adapter/scene-text-session.test.ts`; each keeps its original assertion and adds the split:

1. `session()` helper — `dirty` → `contentDirty` + `spansDirty` (both default false).
2. "a freshly seeded session is CLEAN" → "…in both channels": asserts BOTH flags false.
3. "typing marks the session dirty" → "typing marks the CONTENT channel": same three transitions,
   now asserting `contentDirty` true AND `spansDirty` false (the added half is the G1 rule).
4. "a CLEAN session re-seeds…" — adds `spansDirty` to the flags asserted after the re-seed.
5. "a DIRTY session keeps its draft" → "a TYPED session…": same case on `contentDirty`, plus a second
   assertion that it also holds when the document moved the spans.
6. "a DIRTY session writes" → "a TYPED session writes its draft": same, on `contentDirty`.
7. "a refused FORMATTING commit reverts…" — the `after` session is now `spansDirty`.

Nine cases added: typing-in-a-formatted-session, formatting-claims-only-spans, the two G1 reseed pins,
the two G1 commit pins (live content vs snapshot; unchanged-model), the two G2 selection pins, and the
G3 token-ref family case in `__tests__/textSpans.test.ts`.

### Gates (round 2)

`npm test` 2234 pass / 0 fail / 0 skipped (2225 + 9; wasm artifact suite RUN, 6 cases).
`npm run design-system:build && npm run lint && npm run build` — 0 errors, the same 2 known
`canvasOperations.ts` unused-var warnings. No browser walk (no live stack this session).

## Residuals / notes for the next session

- F4's component plumbing (settle latch, refocus-on-refusal) is React and therefore not unit-tested;
  its RULES are pure and pinned (`textEditSessionEnds` / `textEditSessionAfterStyleCommit`).
- The review cited `scene-artifact-canvas.tsx:281-285` for the false C-9 claim; at `098f243c` those
  lines are the props interface. The real claim was the `handleDoubleClick` docstring (~1434) — that
  is what was corrected.
- Refocus-on-refusal is best-effort (`element.focus()` inside a blur handler); the session stays open
  either way, so a lost focus fight costs nothing but a click.
- No browser walk was run for this wave (no live stack in this session).
