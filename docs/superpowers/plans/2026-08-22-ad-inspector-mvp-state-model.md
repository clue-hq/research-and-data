# AD4.R — Ad-Inspector MVP State Model (retire the third source of truth)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Per the standing session rule, **Opus implements every task; the orchestrating session reviews every diff inline.**

**Goal:** Make the platform ad editor's React inspector a pure projection of the accepted engine scene — the MVP editor's state model — by retiring the inspector controller's long-lived copies of document values, so a scene-backed control reads the live hydrated scene on every render and holds local state only while the user is actively typing in it.

**Architecture:** Three substrate moves land first and are individually inert or strictly-safer: (1) the canvas mirrors an **accepted** apply's scene up to the session **synchronously** (today it arrives one passive-effect render late — the documented reason the alt-text `seen` hack exists); (2) the shared `useInspectorController` gains an opt-in **live-hydration mode** in which returned state is composed per render as `{...uiState, ...hydrated}` and every value setter **dispatches only** (never `setState`); (3) `InspectorInput` gains an opt-in **self-drafting commit mode** (draft while typing, one write on blur/Enter, no-op commits suppressed, draft cleared on commit). Then the three bound ad schemas cut over one at a time, each cutover **deleting** the drift band-aids that schema carries (`useAdColorRow.shown`, the Custom-W/H committed/draft/seen triple, the stroke mint mirrors, the alt-text triple, `RadiusControls`' scene-lane committed snapshot). Finally the `inspectorGeneration` remount machinery is retired — live derivation makes it redundant. **The website lane is untouched**: the controller's default stays exactly today's mount-seeded behavior, and the web migration is recorded as a follow-up with its own transport consideration (web writes are async HTTP; the ad lane's engine is local and synchronous, which is what makes this model flicker-free here).

**Tech Stack:** Next.js 16, React 19, TypeScript, `node:test` via `tsx --test` (pure decision modules only — no DOM renderer), the AD1-extracted scene engine (`lumen_wasm` via CanvasKit).

**Spec:** §Design record below (this plan carries its own spec — the founder ruling is the conversation of 2026-08-22: "Frontend React should exactly be the observer of what the scene engine gives and renders… the React Inspector value [must be] a projection of the accepted scene value") + `docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md` (the parent plan; this slice inserts between AD4.A and AD4.B) + `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` (presentation contract, unchanged by this slice).

---

## Global Constraints

Copied from the parent plan's inherited laws. Every task's requirements implicitly include these.

- **Dummy UI is presentation truth and ceiling.** No new visible chrome, classes, icons, or copy. This slice changes *state ownership*, never markup — every task's diff should be reviewable as "same DOM, different data flow" (the two exceptions are additive optional props on existing primitives, which render nothing by themselves).
- **Process:** Opus implements; the orchestrating session reviews every diff inline; TDD on pure modules; browser proof + local commit per task; **never push**; **no AI attribution in commits** (no `Co-Authored-By: Claude`, no "Generated with" footers).
- **Gates per task:** `cd apps/frontend && npm run design-system:build && npm test && npm run lint && npm run build`. Root `make check` at slice close (Task 9).
- **Test runner is `find src -name '*.test.ts' | xargs tsx --test`** — no `.test.tsx`, no DOM renderer. Hook/component logic that needs testing lives in pure decision modules.
- **Components never import `data/` or the engine** (eslint `no-restricted-imports` enforces); adapters may import data-layer constants.
- **Never key-remount the inspector on a document version / write token** (parent-plan trap #8 / contract §4). This slice *strengthens* that rule: by its end the only remount key is the selected node id.
- **Frontend only.** Zero Python, zero `subsystems/`, zero edits to the verbatim `engine/scene/**` ports.
- Browser proofs run against the real stack (`:3033` web / `:8032` platform API / `:8010` design API), verifying claims against the design API's own document JSON, never only against the UI that wrote it. The seeded ad document is restored node-identical after every proof (the AD4 discipline).

---

## Design record (the spec this plan implements)

### The defect

The platform already has the MVP's engine loop: inspector event → adapter builds `Operation` → WASM engine accepts/refuses → accepted scene repaints the canvas and mirrors up to the session (`use-scene-editing-session.ts:125`) → `hydrated` recomputes from it on every scene change (`use-scene-editing-session.ts:220`). The live projection the MVP renders from **already exists, in the panel's own vocabulary** (`SceneInspectorState` is `Partial<InspectorPresentationState>`).

The defect is one design decision: `useInspectorController` copies `hydrated` into `useState` **once, in a lazy initializer** (`use-inspector-controller.ts:240`), and `setValue` writes the controller's copy *before* dispatching the write event (`use-inspector-controller.ts:255-256`). That copy is an independently editable second owner of document values — the "third state" (controller copy / engine scene / server document). Every AD4 sub-slice shipped at least one defect of the shape *"a control displays or commits a value the document does not have, or a legitimate edit is silently swallowed"*, and each was patched with a local mirror (`shown`, `custom.committed/draft`, `altText.committed/draft/seen`, `RadiusControls.committed`, the stroke mints, `customSizeForPreset` re-seeds, the `inspectorGeneration` remount). Those patches are all correct individually and all evidence of the same missing invariant.

### The target invariant (the MVP's)

> **Only the accepted engine scene owns document values.** The canvas and the inspector are both projections of it; the server persists and reconciles it. React keeps state only for facts that do not claim to be document truth: open sections, AI prompts, staged candidates, UI view choices, and a draft while a field is focused.

Field behavior, uniformly:

```text
Not being edited → display the live hydrated value (the accepted scene)
Being typed in   → display the local draft
Blur/Enter       → suppress no-ops, dispatch ONE write event, clear the draft
Engine accepts   → new scene arrives in the same React batch (Task 1) → display re-derives
Engine refuses   → scene unchanged → display shows the unchanged document value
```

Why this is flicker-free on the ad lane and NOT automatically portable to the web lane: `window.dispatchEvent` is synchronous, the write listener (`use-scene-inspector-writes.ts:266`) maps and applies in the same call stack, and `engine.applyOperations` is a synchronous WASM call — so with Task 1's synchronous mirror, the draft-clear and the new-scene adoption land in **one React batch**. The website lane has no local engine; its writes are HTTP round-trips, so the same draft-clear rule would visibly revert a field for the duration of a network call. The web migration therefore needs its own design (optimistic hydration or draft-until-arrival) and is **out of scope here**, recorded in Task 9.

### Rulings preserved (nothing in this slice may weaken them)

- **§4 / trap #8** — no remount on a write token. Live derivation is derivation, not remounting; Task 8 removes the last non-selection remount trigger.
- **The addressing gates** (`canvasWriteTarget`, the node-path gate) and the **one-listener-per-lane** discipline — untouched.
- **D10 reconcile posture** (note + reload + resync) — untouched; Task 8 only changes how the reloaded values reach the panel (derivation instead of remount).
- **A39/A41 async document/node guards** on upload/generate/accept — untouched; deriving display state does not protect a delayed upload, those guards still do.
- **A7's commit-on-blur number model** (`commitInspectorNumber`) — generalized, not weakened.
- **A38** (every placement path carries stored alt text forward) — the write side, untouched.
- **A36/A40** (both review tiles; review outlives the lock) — untouched.
- **The §1.6 token policy** (brand pick writes a token, custom hex detaches) — untouched at the write adapter; only the *display* path simplifies.

### Rulings superseded by this slice (each was a correct patch for the state model this slice removes)

| Ruling / mechanism | Where it lives today | What replaces it |
|---|---|---|
| A27 — dirty check against a `committed` snapshot | `RadiusControls` (`inspector-primitives.tsx:611-641`), alt text (`image-inspector.tsx:921-971`), Custom W/H (`image-inspector.tsx:534-572`) | Compare the draft against the **live document value** (`values`/`state` prop, now live) — `fieldCommit` in Task 3. *(Scene lane only: `RadiusControls`' WEB branch keeps its committed snapshot until the web lane's own migration.)* |
| A26/A28 — post-commit restate mirrors (`restate`, `uniformRadius` re-derive) | `RadiusControls` scene branch | Deleted; hydrate already derives `all`, and the live values prop re-states everything in the same batch |
| A29's *recording* half — "a locked commit records nothing" | `RadiusControls.commitAll`, `commitAltText` | Structural: nothing records anything anymore. The `locked` guard survives only to skip a doomed dispatch |
| A15.2's display-commit re-seeds + `useAdColorRow.shown` | `image-inspector.tsx:136-171,595-612` | Display derives from live `hydrated`; the pure `backgroundFillCommits` decision stays as the write chooser |
| The Custom-W/H `customSizeForPreset` re-seed | `image-inspector.tsx:613-619`, `scene-hydrate.ts:404-415` | The boxes read live `state.customWidth/Height`, which `hydrateSceneCanvasState` always states |
| The stroke mint display mirrors (`commitStrokeColor`, `changeStrokeWidth`'s `setShown`) | `image-inspector.tsx:433-457` | The write adapter still mints (ruling A9's home); the display derives from the minted scene in-batch |
| The alt-text `committed/draft/seen` triple | `image-inspector.tsx:947-971` | The self-drafting input over live `state.altText` |
| A31 — refused-typed-text retention + canonical restate (`radiusCommitText` in the corner commit) *(row added at T7, per its review)* | `RadiusControls` scene branch | Deleted; a refused commit clears the draft and the display reverts to the live document value (this plan's field-behavior table); `radiusCommitText` survives adapter/test-side only |
| FIX 2 — the Fill preview's `hydrated?.imagePreviewSrc ?? state.imagePreviewSrc` out-ranking *(row added at T7)* | `image-inspector.tsx` | Collapsed to `src={state.imagePreviewSrc}` — live composition makes the two arms identical (hydrate omits absent keys), so the guarantee is structural |
| `inspectorGeneration` + `reloadPendingRef` remount-on-reload-arrival | `use-scene-editing-session.ts:106-139`, `editor-surface.tsx:181-197`, **and the chats-route twin at `chat-surface.tsx:347`** (found at T8's grep gate) | Live derivation — a reloaded scene changes `hydrated`, and every unfocused field re-reads it with no remount; both mounts moved together |

### Disclosed behavior change (founder-RATIFIED 2026-08-22)

The ad text schema's **Font size**, **Stroke width**, **Position X/Y**, and **Rotation** inputs move from per-keystroke writes to the commit-on-blur/Enter model (superseding AD4.0's "§1.2's Size box keeps its per-keystroke behaviour" note; Position/Rotation added by the dated T6 amendment below after the Task 4 review exposed the plan gap). Rationale: per-keystroke, typing `24` persists document versions `2` then `24` — two undo steps for one intent, the same defect class A7 closed for the gradient fields. This matches the field-behavior spec above and is the MVP's *intended* (if mislabeled — its `onCommit` fired per keystroke) contract. **Founder ruling at plan approval: commit-on-blur/Enter for now; a future slice MAY move typed fields to per-keystroke writes** (which would need live-preview ops or write coalescing to avoid the one-version-per-digit defect — record that constraint if it is ever picked up). Disclose in the Task 6 commit message and the Task 9 close-out.

### Founder-gate register

| Gate | What | Blocks | Owner action |
|---|---|---|---|
| **G-H** | The disabled treatment for locked/read-only fields — adopting upstream's `disabled={selectedNode.locked}` posture using the shell's one authored `:disabled` treatment (`.sharePrimaryButtonWide:disabled`, opacity 0.45 + `cursor: wait`; a field variant needs a founder-approved look) | **Task 10 only.** Tasks 1–9 do not depend on it: under live derivation a refused interaction is already honest (the display never moves) | Orchestrator produces browser screenshots of a locked node's fields with the proposed treatment; founder rules |

---

## File map (what changes by the end)

```
apps/frontend/src/features/
  design-editor/components/scene-artifact-canvas.tsx     MODIFY  T1  (synchronous accepted-scene mirror)
  chat-shell/hooks/use-inspector-controller.ts           MODIFY  T2  (live-hydration mode + composeInspectorState)
  chat-shell/hooks/inspector-live-state.test.ts          CREATE  T2
  chat-shell/components/inspector-field-draft.ts         CREATE  T3  (pure draft/commit decisions)
  chat-shell/components/inspector-field-draft.test.ts    CREATE  T3
  chat-shell/components/inspector-primitives.tsx         MODIFY  T3  (InspectorInput self-drafting), T7 (RadiusControls scene branch)
  chat-shell/components/image-inspector.tsx              MODIFY  T4–T7 (live flags, then band-aid deletion per schema)
  design-editor/adapter/scene-hydrate.ts                 MODIFY  T5  (delete customSizeForPreset if orphaned)
  design-editor/adapter/scene-hydrate.test.ts            MODIFY  T5
  design-editor/hooks/use-scene-editing-session.ts       MODIFY  T8  (retire inspectorGeneration machinery)
  chat-shell/components/editor-surface.tsx               MODIFY  T8  (key on node id only)
docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md   MODIFY  T9 (record AD4.R before Lane B)
_memory/2026-08-22-ad4r-mvp-state-model.md               CREATE  T9
```

**File-map amendments recorded at execution** (each ruled mid-task; the ledger and `_memory` close-out carry the rulings): `chat-surface.tsx` MODIFY T8 (the chats-route twin mount, missing from this map — plan defect #2); `scene-apply.test.ts` / `scene-image-ai.test.ts` / `scene-hydrate.test.ts` MODIFY T7 (8 source-text ruling guards rewritten to pin the live-derivation mechanism — plan defect #1; "no direct tests" below was wrong); `use-scene-image-ai.ts` MODIFY T8 (comment-only: its remount-premise doc block).

Deliberately **not** touched: `web-inspector.tsx`, `use-web-editing-session.ts`, `use-inspector-writes.ts` (web lane), `scene-apply.ts` (the write adapter is correct and is the other half of the §1 contract), `use-scene-inspector-writes.ts`, `use-scene-manual-edits.ts`, `use-scene-replace-image.ts`, everything under `engine/scene/**`.

---

### Task 1: Synchronous accepted-scene mirror

**Files:**
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx:433-459` (the `controls` memo)

**Interfaces:**
- Consumes: the existing `onSceneChangeRef` (`scene-artifact-canvas.tsx:658-661`), `outcome.scene` from `engine.applyOperations`, the component's `pageId` state and `documentId` prop.
- Produces: after an **accepted** `applyOperations`, the session's `onSceneChange(scene, pageId, documentId)` has already run **inside the same synchronous call** — so any `setState` the caller performs in the same event handler batches with the session's `setLoaded`, and `hydrated` is current on the very next render. The passive-effect mirror stays (it still owns the load/reload paths and the relaid-scene adoption); its later re-fire with the final rendered scene is an idempotent `setLoaded`.

**Why this is safe standalone:** every consumer of `hydrated` today either ignores post-mount changes (the mount-seeded controller) or guards with a last-seen comparison (the alt-text `seen` triple — which re-seeds to the same text it just committed, a no-op). Making the value arrive earlier changes no displayed value; it only removes the 1–2 render window the `image-inspector.tsx:940-946` comment documents.

- [ ] **Step 1: Implement.** In the `controls` memo's `applyOperations`, after `refresh()`:

```tsx
      applyOperations: (operations) => {
        if (!engine) {
          return null;
        }
        const outcome = engine.applyOperations(operations);
        // `refresh()` is BOTH halves of "the canvas owns it": it adopts the
        // engine's post-apply scene as the rendered one (repaint) and, through
        // the effect below, mirrors that same scene up to the session — which
        // rehydrates the inspector and rebuilds the layer tree. A rejected
        // batch changed nothing, so it repaints nothing.
        if (outcome.accepted) {
          refresh();
          // AD4.R: the accepted scene ALSO mirrors up synchronously, so a
          // commit handler's own setState and the session's scene adoption land
          // in one React batch — the inspector's live-derived fields re-read
          // the post-write document on the very next render, with no frame in
          // between showing the pre-write value. The passive effect below still
          // fires afterwards with the final rendered (possibly relaid) scene;
          // that second setLoaded is idempotent. This is the MVP editor's own
          // shape: EditorApp installs result.scene in the accept path.
          onSceneChangeRef.current?.(outcome.scene, pageId, documentId);
        }
        return outcome;
      },
```

Note `onSceneChangeRef` is declared *below* the memo today (`:658`); refs are stable across renders and this call happens at event time, long after mount — but move the `onSceneChangeRef` declaration + its sync effect **above** the `controls` memo so the reader meets the ref before its first use, and so TS sees it in scope.

- [ ] **Step 2: Run the full frontend gate.** `cd apps/frontend && npm run design-system:build && npm test && npm run lint && npm run build`. Expected: green (no test exercises the canvas component directly — the runner has no DOM; the suite proves nothing else broke).
- [ ] **Step 3: Browser sanity proof.** Against the seeded ad: type a corner radius, blur; confirm in the browser that the canvas and panel repaint together and the design API's document JSON carries the value. Confirm alt-text commit shows no flash. Restore the document.
- [ ] **Step 4: Commit.**

```bash
git add src/features/design-editor/components/scene-artifact-canvas.tsx
git commit -m "feat(ad-editor): AD4.R-1 mirror the accepted scene up synchronously

An accepted applyOperations now calls onSceneChange in the same call
stack (the MVP editor's own accept-path shape), so a commit handler's
draft-clear and the session's scene adoption land in one React batch.
Groundwork for deriving inspector values live: without it, every
live-derived field would show the pre-write value for the 1-2 renders
the passive-effect mirror takes (the documented reason the alt-text
'seen' triple exists). The passive effect stays for load/reload/relaid
scenes; its later re-fire is an idempotent setLoaded."
```

---

### Task 2: Controller live-hydration mode

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-inspector-controller.ts`
- Test: `apps/frontend/src/features/chat-shell/hooks/inspector-live-state.test.ts` (create)

**Interfaces:**
- Consumes: nothing new — the existing `hydrated?: Partial<InspectorPresentationState>` parameter, which callers already rebuild per render from the live scene.
- Produces (later tasks rely on these exact names):
  - `export interface InspectorControllerOptions { liveHydration?: boolean }` — new optional 5th parameter of `useInspectorController`.
  - `export function composeInspectorState(uiState: InspectorPresentationState, hydrated: Partial<InspectorPresentationState> | undefined): InspectorPresentationState` — the pure per-render composition: `hydrated` wins every key it carries **except** `openSections`, which always comes from `uiState`.
  - In live mode, `setValue` / `setNestedValue` / `setPaddingAxis` / `setRadiusAll` **dispatch only** (no `setState`). `toggleSection` and `requestAction` are unchanged in both modes.
  - Default behavior (no options / `liveHydration` falsy) is **byte-for-byte today's**: the web inspector and the dummy fixture paths compile and behave unchanged.

- [ ] **Step 1: Write the failing tests** (`inspector-live-state.test.ts`):

```ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  composeInspectorState,
  DEFAULT_STATE,
  type InspectorPresentationState,
} from "./use-inspector-controller";

// A representative uiState: the real DEFAULT_STATE with a few fields moved off
// their defaults, standing in for stale mount-time copies.
const base = (): InspectorPresentationState => ({
  ...structuredClone(DEFAULT_STATE),
  fillMode: "Fill",
  radius: { all: "9", bottomLeft: "9", bottomRight: "9", topLeft: "9", topRight: "9" },
  openSections: { ...DEFAULT_STATE.openSections, fill: false },
});

test("hydrated wins every key it carries", () => {
  const composed = composeInspectorState(base(), {
    fillMode: "Fit",
    radius: { all: "", bottomLeft: "4", bottomRight: "4", topLeft: "4", topRight: "96" },
  });
  assert.equal(composed.fillMode, "Fit");
  assert.deepEqual(composed.radius, { all: "", bottomLeft: "4", bottomRight: "4", topLeft: "4", topRight: "96" });
});

test("keys hydration does not carry fall back to uiState", () => {
  const composed = composeInspectorState(base(), { fillMode: "Fit" });
  assert.equal(composed.fontFamily, base().fontFamily);
});

test("openSections always come from uiState, never hydration", () => {
  const composed = composeInspectorState(base(), {
    openSections: { ...base().openSections, fill: true },
  } as never);
  assert.equal(composed.openSections.fill, false);
});

test("undefined hydration composes to uiState unchanged", () => {
  assert.deepEqual(composeInspectorState(base(), undefined), base());
});
```

The import requires adding `export` to the existing `const DEFAULT_STATE` in `use-inspector-controller.ts` (rename nothing) so the test composes over the real shape rather than a hand-written one — do that edit in Step 3 alongside the implementation.

- [ ] **Step 2: Run to verify failure.** `npx tsx --test src/features/chat-shell/hooks/inspector-live-state.test.ts` → FAIL (`composeInspectorState` not exported).
- [ ] **Step 3: Implement.**

```ts
export interface InspectorControllerOptions {
  /**
   * AD4.R: the MVP state model. When true, the returned `state` is composed
   * PER RENDER as `{...uiState, ...hydrated}` (openSections excepted — those
   * are UI facts the panel owns), and every value setter dispatches its write
   * event WITHOUT recording the value locally: the document answers through
   * the next hydration, which on the ad lane arrives in the same React batch
   * (the Task-1 synchronous mirror). False (the default) is the original
   * mount-seeded behavior, byte-for-byte — the web inspector and the dummy
   * fixture paths run on it unchanged, pending the web lane's own migration.
   */
  liveHydration?: boolean;
}

export function composeInspectorState(
  uiState: InspectorPresentationState,
  hydrated: Partial<InspectorPresentationState> | undefined,
): InspectorPresentationState {
  if (!hydrated) return uiState;
  return { ...uiState, ...hydrated, openSections: uiState.openSections };
}
```

In `useInspectorController(collapsedSections, selectionType, hydrated, addressing, options)`:

```ts
  const live = options?.liveHydration === true;
  const [uiState, setUiState] = useState<InspectorPresentationState>(() => ({
    /* the existing initializer, unchanged */
  }));
  const state = useMemo(
    () => (live ? composeInspectorState(uiState, hydrated) : uiState),
    [hydrated, live, uiState],
  );
```

Each of `setValue`, `setNestedValue`, `setPaddingAxis`, `setRadiusAll`: wrap the existing `setState` call in `if (!live) { … }`; the `dispatchInspectorEvent` call runs in both modes unchanged. (`setRadiusAll`'s `clearCorners` mirror is part of the guarded `setState` — in live mode the document's own cleared corners arrive through hydration.) Add `live` to each callback's dependency array. `toggleSection` keeps writing `uiState` in both modes.

- [ ] **Step 4: Run tests + full gate.** New test PASS; the whole suite green (no caller passes the option yet, so `inspector-event-addressing.test.ts` and `inspector-commit-model.test.ts` are unaffected).
- [ ] **Step 5: Commit.**

```bash
git add src/features/chat-shell/hooks/use-inspector-controller.ts src/features/chat-shell/hooks/inspector-live-state.test.ts
git commit -m "feat(ad-editor): AD4.R-2 controller live-hydration mode (inert)

Opt-in liveHydration option: state composes {...uiState, ...hydrated}
per render (openSections stay UI-owned) and value setters dispatch
without recording locally — the accepted scene is the only owner of
document values. Default behavior unchanged; no caller opts in yet."
```

---

### Task 3: Self-drafting `InspectorInput` + the pure draft module

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/inspector-field-draft.ts`
- Test: `apps/frontend/src/features/chat-shell/components/inspector-field-draft.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx:467-523` (`InspectorInput`)

**Interfaces:**
- Produces (later tasks rely on these exact names):
  - `export function fieldDisplay(draft: string | null, value: string): string` — `draft ?? value`.
  - `export function fieldCommit(draft: string | null, value: string): string | null` — the value to write, or `null` when there is no draft or the draft equals the document value (the A27 dirty check, made structural: the comparison target is the **live** document value, which cannot be stale under live hydration).
  - `InspectorInput` gains `onCommitValue?: (value: string) => void`. When supplied, the input **owns its draft**: display is `fieldDisplay(draft, value)`; typing sets the draft (and still calls `onChange` if one is passed — it becomes optional); blur/Enter computes `fieldCommit(draft, value)`, calls `onCommitValue` iff non-null, and clears the draft either way. Without `onCommitValue`, the input is byte-for-byte today's (controlled `value` + `onChange`, optional `onCommit`).
- Consumes: nothing from Tasks 1–2 (independently landable).

- [ ] **Step 1: Write the failing tests** (`inspector-field-draft.test.ts`):

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { fieldCommit, fieldDisplay } from "./inspector-field-draft";

test("display prefers the draft while one exists", () => {
  assert.equal(fieldDisplay("10", "32"), "10");
  assert.equal(fieldDisplay("", "32"), "");     // an emptied box shows empty
  assert.equal(fieldDisplay(null, "32"), "32"); // no draft → the document value
});

test("a commit is the draft, unless there is nothing new to say", () => {
  assert.equal(fieldCommit("96", "32"), "96");
  assert.equal(fieldCommit(null, "32"), null);  // never typed → no write
  assert.equal(fieldCommit("32", "32"), null);  // A27 structural: same value → no write
  assert.equal(fieldCommit("", "32"), "");      // an explicit clear IS a commit —
  // the write adapter decides what an empty string means per row (radius: no
  // write; alt text: clear), exactly as it does today.
});
```

- [ ] **Step 2: Run to verify failure** → FAIL (module missing).
- [ ] **Step 3: Implement the module** (two functions, doc comments stating the invariant: "the comparison target is the live document value — under live hydration it cannot be stale, which is what retires A27's committed snapshots").
- [ ] **Step 4: Extend `InspectorInput`.**

```tsx
export function InspectorInput({
  ariaLabel, className, leading, onChange, onCommit, onCommitValue,
  placeholder, prefix, readOnly = false, suffix, value,
}: {
  ariaLabel: string;
  className?: string;
  leading?: ReactNode;
  /** Optional once `onCommitValue` exists: a self-drafting field needs no
   * per-keystroke channel. Every existing caller keeps passing it. */
  onChange?: (value: string) => void;
  onCommit?: () => void;
  /**
   * AD4.R (the MVP state model): when supplied, the input drafts locally while
   * being typed in and commits ONCE on blur/Enter — `fieldCommit` suppresses
   * the no-op re-type, and the draft clears on commit either way. `value` must
   * then be the LIVE document value (the live-hydrated controller state): the
   * accepted write lands in the same React batch (the Task-1 mirror), so the
   * cleared draft reveals the just-written value with no frame in between; a
   * refused write reveals the unchanged one, which is the honest display.
   * Mutually exclusive with `onCommit` (the caller-managed draft protocol) —
   * supplying both is a programming error and `onCommitValue` wins.
   */
  onCommitValue?: (value: string) => void;
  placeholder?: string;
  prefix?: string;
  readOnly?: boolean;
  suffix?: string;
  value: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const selfDrafting = onCommitValue !== undefined;
  const shown = selfDrafting ? fieldDisplay(draft, value) : value;
  const commitSelf = () => {
    const commit = fieldCommit(draft, value);
    setDraft(null);
    if (commit !== null) onCommitValue?.(commit);
  };
  return (
    <span className={`${styles.inspectorControl} ${styles.inspectorInputControl} ${className ?? ""}`}>
      {leading}
      {prefix ? <span className={styles.fieldPrefix}>{prefix}</span> : null}
      <input
        aria-label={ariaLabel}
        inputMode="text"
        onBlur={selfDrafting ? commitSelf : onCommit ? () => onCommit() : undefined}
        onChange={(event) => {
          if (selfDrafting) setDraft(event.target.value);
          onChange?.(event.target.value);
        }}
        onKeyDown={
          selfDrafting
            ? (event) => { if (event.key === "Enter") commitSelf(); }
            : onCommit
              ? (event) => { if (event.key === "Enter") onCommit(); }
              : undefined
        }
        placeholder={placeholder}
        readOnly={readOnly}
        value={shown}
      />
      {suffix ? <span className={styles.fieldPrefix}>{suffix}</span> : null}
    </span>
  );
}
```

(The `useState` import already exists in the file. DOM, classes, aria are untouched — presentation ceiling holds.)

- [ ] **Step 5: Run tests + full gate.** New tests PASS; suite green (no caller passes `onCommitValue` yet; `onChange` loosening compiles because every existing caller supplies it).
- [ ] **Step 6: Commit.**

```bash
git add src/features/chat-shell/components/inspector-field-draft.ts src/features/chat-shell/components/inspector-field-draft.test.ts src/features/chat-shell/components/inspector-primitives.tsx
git commit -m "feat(ad-editor): AD4.R-3 self-drafting InspectorInput (inert)

onCommitValue turns the input into the MVP field: draft while typing,
one write on blur/Enter, no-op re-types suppressed against the LIVE
document value (fieldCommit — A27's dirty check made structural),
draft cleared on commit. No caller opts in yet; existing onChange /
onCommit protocols unchanged."
```

---

### Task 4: Flip the ad panel to live hydration (flag only — no band-aid removal yet)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (the four `useInspectorController` call sites: header `:1076`, text `:410`, canvas `:507`, image `:914`)

**Interfaces:**
- Consumes: Task 2's `InspectorControllerOptions`; Task 1's in-batch hydration.
- Produces: every bound ad schema's `state` is live-composed. The existing band-aid local states (`shown`, `custom`, `altText`, `strokeWidth`) still sit **above** the controller and keep their current displays — this task changes behavior only where controls read `state.*` directly, and only in one direction: a **refused** write can no longer stick (the select/toggle snaps to the document because it never left it). Accepted writes display identically (the value now arrives via hydration in the same batch instead of via the local echo).

**Why flag-first:** it is the smallest reviewable step that closes the whole "refused write leaves the panel lying" family at once, and it proves the composition under every already-shipped control before any deletion. A reviewer can reject a band-aid removal without rejecting the model flip.

- [ ] **Step 1: Implement.** At each of the four call sites, pass the options argument. Text schema, exactly:

```tsx
  const initial = { fontWeight: "600 Semi Bold", ...hydrated };
  const controller = useInspectorController([], "text", initial, addressing, {
    // AD4.R: live only when a real scene is behind the panel — the dummy
    // fixture path (no hydration) stays the interactive mock it shipped as.
    liveHydration: hydrated != null,
  });
```

Canvas schema: same with `initial = { sizePreset: SIZE_PRESETS[0], ...hydrated }`. Image schema and the header controller: `{ liveHydration: hydrated != null }` with their existing `hydrated ?? undefined` argument. Note the text/canvas `initial` objects are rebuilt from the live `hydrated` prop every render, so they are the live merge source too — the schema-default keys (`fontWeight`, `sizePreset`) ride along and win only when hydration doesn't carry that key, which is exactly today's mount semantics extended to every render.

- [ ] **Step 2: Full gate.** Expected green — no test pins the mount-copy behavior of these four call sites.
- [ ] **Step 3: Browser proof (the refusal-honesty walk).** Against the seeded ad, verify each and verify the document JSON after each:
  1. Lock the image node (header lock). Change the **Mode** select → the select visibly stays on the document's value (before this task it stuck on the picked one); document unchanged.
  2. Still locked: click a **font weight** on the headline → display stays; document unchanged.
  3. Unlock → both writes land and display normally.
  4. The **lock toggle itself** round-trips (it is a `state.locked` read — now live).
- [ ] **Step 4: Restore the seeded document; commit.**

```bash
git add src/features/chat-shell/components/image-inspector.tsx
git commit -m "feat(ad-editor): AD4.R-4 ad schemas read live-hydrated state

All four ad controller instances opt into liveHydration (real scene
only; the dummy fixture path keeps mount semantics). Controls reading
state.* now project the accepted scene: a refused write can no longer
leave a select/toggle stating a value the document does not have.
Band-aid local mirrors are untouched here — removed schema-by-schema
in the next three tasks."
```

---

### Task 5: Canvas schema cleanup (Custom W/H triple, preset re-seed)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`AdCanvasInspector`, `:494-657`)
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-hydrate.ts` + `scene-hydrate.test.ts` (only if `customSizeForPreset` is orphaned — Step 3)

**Interfaces:**
- Consumes: Task 3's `onCommitValue`; Task 4's live `state.customWidth`/`state.customHeight`/`state.sizePreset` (hydrate **always** states them — `hydrateSceneCanvasState`, `scene-hydrate.ts:882-905`).
- Produces: `AdCanvasInspector` with one small UI-only state: `const [customChosen, setCustomChosen] = useState(false)` — the "Custom" entry names no document size, so choosing it is a **view choice**, the one legitimate schema-local UI fact here.

- [ ] **Step 1: Implement.**
  - Delete the `custom` `useState` triple, `draftCustomSize`, `commitCustomSize` (`:553-572`) and the `changeSizePreset` re-seed (`:613-619`, including the `customSizeForPreset` import).
  - The W/H inputs become self-drafting over live state:

```tsx
            <InspectorInput ariaLabel="Custom width" onCommitValue={(value) => setValue("customWidth", value)} prefix="W" value={state.customWidth} />
            <InspectorInput ariaLabel="Custom height" onCommitValue={(value) => setValue("customHeight", value)} prefix="H" value={state.customHeight} />
```

  - The preset select:

```tsx
  // AD4.R: "Custom" is a VIEW choice, not a document fact — it names no size,
  // writes nothing, and only reveals the W/H boxes (which read the live page
  // size hydrate always states). Everything else the select shows is the
  // document's own preset match. Picking a real preset dispatches the write
  // and drops the view choice; the document answers through hydration.
  const [customChosen, setCustomChosen] = useState(false);
  const shownPreset = customChosen ? "Custom" : state.sizePreset;
  const changeSizePreset = (label: string) => {
    if (label === "Custom") {
      setCustomChosen(true);
      return;
    }
    setCustomChosen(false);
    setValue("sizePreset", label);
  };
```

    Render `value={shownPreset}` on the select and gate the W/H row on `shownPreset === "Custom"`.
- [ ] **Step 2: Full gate.**
- [ ] **Step 3: Orphan check.** `grep -rn "customSizeForPreset" apps/frontend/src` — if the only remaining references are its definition and its tests, delete the function and its `scene-hydrate.test.ts` cases (its doc comment says it exists solely for the re-seed this task removed). If anything else consumes it, leave it and note the consumer in the commit message.
- [ ] **Step 4: Browser proof** (each item verified against the document JSON, both canvas entry states — empty selection AND artboard selected):
  1. Page at 1200×1200 → pick "Story" → select, W/H boxes, and artboard all state 1080×1920 in one paint.
  2. Pick "Custom" → **no write**; boxes show 1080/1920 (the real size, not a stale seed).
  3. Type W `1100`, blur → exactly ONE new document version at 1100×1920; typing `1100` again and blurring writes **nothing** (the fieldCommit no-op).
  4. Type `108`, then keep typing to `1080`, blur → ONE version at 1080 wide (no 1/10/108 intermediate versions).
  5. Solid → gradient → Solid walk: the select, the swatch, and the artboard agree at every step (the AD4.0 S2 three-surfaces defect stays closed under the new model; `backgroundFillCommits` is untouched as the write chooser — its display half now derives).
- [ ] **Step 5: Restore the seeded document; commit.**

```bash
git add src/features/chat-shell/components/image-inspector.tsx src/features/design-editor/adapter/scene-hydrate.ts src/features/design-editor/adapter/scene-hydrate.test.ts
git commit -m "refactor(ad-editor): AD4.R-5 canvas schema derives live; W/H triple retired

Custom W/H are self-drafting fields over the live page size hydrate
always states; the committed/draft mirror, the preset re-seed and
customSizeForPreset go with it. 'Custom' survives as the one honest
UI-only fact here: a view choice that names no size and writes
nothing."
```

---

### Task 6: Color rows + text schema cleanup (`shown`, stroke mirrors, per-keystroke writes)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`useAdColorRow` `:136-171`, `AdTextInspector` `:394-492`)

**Interfaces:**
- Consumes: live `state.textColor` / `state.strokeColor` / `state.strokeWidth` / `state.backgroundColor` (Task 4), the in-batch mirror (Task 1), `onCommitValue` (Task 3).
- Produces: `useAdColorRow` shrinks to `{ color, onColorChange, onTokenChange, value }` — **no `shown` state, no `setShown` export**. Its `value` IS `hydratedValue` (live). Callers that used `setShown` (the stroke mint mirror) are deleted in the same diff, so the file never has a dangling consumer.

- [ ] **Step 1: Implement.**
  - `useAdColorRow`: delete `shown`/`setShown`; `value = hydratedValue`; handlers dispatch only:

```tsx
function useAdColorRow({ hydratedValue, onHex, onToken, paletteOptions }: { /* unchanged types minus nothing */ }) {
  const palette = useScenePalette();
  // AD4.R: the row shows the DOCUMENT's value — a token name or a colour —
  // which under live hydration is current in the same batch as the write it
  // dispatched (a brand pick surfaces as the token's name, a detaching hex as
  // the hex, a refused write as the unmoved old value). The 'shown' draft this
  // hook carried was the mount-seeded model's patch for exactly that gap.
  const value = hydratedValue;
  return {
    color: scenePaletteColor(palette, value) ?? value,
    onColorChange: onHex,
    onTokenChange: paletteOptions && onToken,
    value,
  };
}
```

  - `AdTextInspector`: delete the `strokeWidth` local state, `commitStrokeColor`, and `changeStrokeWidth` (`:433-457`). The stroke color row dispatches directly (`onHex: (hex) => setValue("strokeColor", hex)`, `onToken: (label) => setValue("tokenStrokeColor", label)`); the minted width/colour now *display* through hydration of the minted scene (ruling A9's write half in `scene-apply.ts` is untouched and remains the single statement of the mint).
  - Stroke width input → `<InspectorInput ariaLabel="Stroke width" onCommitValue={(value) => setValue("strokeWidth", value)} value={state.strokeWidth} />`.
  - Font size input → `<InspectorInput ariaLabel="Font size" onCommitValue={(value) => setValue("fontSize", value)} value={state.fontSize} />` (the disclosed per-keystroke → commit change).
  - **[AMENDED 2026-08-22, T4-review ruling]** The text schema's other per-keystroke numeric inputs migrate the same way in this task — they have no band-aid, so under live composition a per-keystroke dispatch whose value the adapter refuses (an emptied box, a trailing `.`, a leading `-`) snaps back mid-typing: Position X → `onCommitValue={(value) => setNestedValue("position", "x", value)}`, Position Y likewise, Rotation → `onCommitValue={(value) => setValue("rotation", value)}`, each keeping its current `value={state.…}` read. Same founder-ratified commit-on-blur/Enter model; add all three to the Step 3 browser proof (type a decimal into Rotation; clear and retype Position X; verify one document version per commit).
  - `AdCanvasInspector`'s `backgroundRow` and `changeBackgroundFill` (`:595-612`): `backgroundRow.onColorChange(commit.value)` becomes plain dispatch through the shrunken row (same call, no `setShown` behind it) — verify the gradient→Solid walk still resolves tokens via `backgroundFillCommits` reading `backgroundRow.value` (now the live hydrated value, which is *more* correct than the draft it replaced: it is the exact fact the write adapter reads off the node).
  - Check for `mintedStrokeWidth`/`mintedStrokeColor` orphaning in the panel: `grep -rn "mintedStroke" apps/frontend/src` — the panel imports go; the `scene-hydrate.ts` exports stay if `scene-apply.ts`/hydrate tests consume them (they state ruling A9's numbers); note the outcome in the commit message.
- [ ] **Step 2: Full gate.**
- [ ] **Step 3: Browser proof** (headline + stroke, document JSON checked each step):
  1. Brand pick on text color → swatch shows the token, document carries the binding.
  2. Custom hex → swatch shows the hex, binding detached.
  3. Stroke width `3` on a strokeless node, blur → ONE version; document mints `#256c70` width 3; the color row beside it states the minted color **without any mirror having set it**.
  4. Lock the node → hex pick → swatch stays on the document's color; unlock → lands.
  5. Font size: type `2`, then `4`, blur → ONE version at 24 (disclosed change: previously two).
- [ ] **Step 4: Restore; commit** (disclose the commit-model change in the message):

```bash
git add src/features/chat-shell/components/image-inspector.tsx
git commit -m "refactor(ad-editor): AD4.R-6 color rows and text schema derive live

useAdColorRow's 'shown' draft, the stroke mint display mirrors and the
strokeWidth local copy are retired — the row states the document's own
value, minted or bound, in the same batch as the write. DISCLOSED
behavior change: Font size and Stroke width move from per-keystroke
writes to commit-on-blur/Enter (supersedes AD4.0's '§1.2 Size stays
per-keystroke' note; one intent is now one document version)."
```

---

### Task 7: Image schema cleanup (alt-text triple, `RadiusControls` scene branch)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`AdImageInspector`, `:901-1026`)
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx` (`RadiusControls`, `:570-780`)

**Interfaces:**
- Consumes: live `state.altText` / `state.radius` / `state.imagePreviewSrc`, `fieldCommit`/`fieldDisplay` (Task 3).
- Produces: `RadiusControls` gains no new props and loses none; its **scene branch** (`onApplyAll` absent) re-bases on live `values` with per-field drafts; the **web branch** (`onApplyAll` present) is byte-for-byte untouched, `committed` snapshot and all — the web lane still runs the mount-seeded model until its own migration.

- [ ] **Step 1: Alt text.** Delete the `documentAltText`/`altText` triple and `commitAltText` (`:947-971`). The input:

```tsx
        <InspectorField label="Alt text">
          <InspectorInput
            ariaLabel="Image alt text"
            // A29's surviving half: a locked node's commit skips the doomed
            // dispatch. Honesty no longer depends on it — nothing records
            // locally — it only spares the adapter a refusal.
            onCommitValue={(value) => { if (!locked) setValue("altText", value); }}
            placeholder="Describe the image"
            value={state.altText}
          />
        </InspectorField>
```

  The sibling re-seed the triple existed for (Replace image overwrites `asset_placement.alt_text`) is now free: the box reads live state, and an unfocused box has no draft to go stale.
  - Also collapse the preview special-case: `src={state.imagePreviewSrc}` replaces `src={hydrated?.imagePreviewSrc ?? state.imagePreviewSrc}` (`:994`) — live state IS the hydrated value now; update the comment to say the primitive follows the live value.
- [ ] **Step 2: `RadiusControls` scene branch.** Keep the component's props and the web branch untouched. Re-shape the internals so the two lanes' state is explicit:

```tsx
  // WEB lane (onApplyAll present): the mount-seeded model, unchanged — its
  // committed/draft snapshot (ruling A27) stays until the web lane's own
  // live-hydration migration.
  // SCENE lane (onApplyAll absent, AD4.R): `values` is LIVE (the ad panel's
  // live-hydrated state), so the five fields are self-drafting projections:
  // draft while typing, commit compared against the live document value
  // (fieldCommit), and NO post-commit mirrors — the document's own corners,
  // including the derived `all`, arrive through hydration in the same batch.
  const scene = !onApplyAll;
  const [drafts, setDrafts] = useState<Partial<Record<RadiusCorner, string>>>({});
  const sceneShown = (corner: RadiusCorner) =>
    fieldDisplay(drafts[corner] ?? null, values[corner]);
  const sceneCommit = (corner: RadiusCorner) => {
    const commit = fieldCommit(drafts[corner] ?? null, values[corner]);
    setDrafts((current) => ({ ...current, [corner]: undefined }));
    if (commit === null || locked) return;
    onChange(corner, commit);
  };
  const sceneApplyAll = () => {
    // The scan button's meaning IS the all-corners write (both lanes' ruling),
    // so it commits the shown value even when unchanged — but an empty value
    // would clear rather than apply, so it is a no-op.
    const value = sceneShown("all");
    if (value.trim() === "" || locked) return;
    setDrafts((current) => ({ ...current, all: undefined }));
    onChange("all", value);
  };
```

  Wire the five `InspectorInput`s and the scan button through `scene ? sceneShown/sceneCommit/sceneApplyAll : <existing draft/commitAll/applyAll>`. Delete the scene-lane arms of `commitAll`/`applyAll`/`restate` and the now-web-only `uniformRadius` mirror usage (`uniformRadius` itself: `grep -rn "uniformRadius" apps/frontend/src` — if the component was its only consumer, delete it; hydrate has its own derivation). Import `fieldCommit`/`fieldDisplay` from `./inspector-field-draft`.
- [ ] **Step 3: Full gate.** Expected: green after updating any `inspector-primitives`-adjacent assertions (none known — the component has no direct tests; the pure logic now lives in the tested draft module).
- [ ] **Step 4: Browser proof** — the walk that was **impossible** before AD4.A's five fix rounds, now structural:
  1. Seeded corners 32/32/96/32: scan `24` → all four land 24 in one version (`{24,24,24,24}` in the JSON).
  2. Restore through the UI: type 32/32/96/32 into the corners — including re-typing values a corner already had at some point — every legitimate edit commits; final JSON exactly 32/32/96/32.
  3. Single corner 9 on a uniform node → the `all` box goes empty (hydrate's derived truth) with **no component mirror**; typing the uniform value into `all` restores it.
  4. Lock the node → scan → nothing dispatched, boxes still state the document.
  5. Replace image → the alt-text box re-states the carried-forward text (A38) with the triple gone; type a new description, Enter → one version; Reject-path check: on a locked node, Enter leaves the box showing the document's text after blur.
- [ ] **Step 5: Restore; commit.**

```bash
git add src/features/chat-shell/components/image-inspector.tsx src/features/chat-shell/components/inspector-primitives.tsx
git commit -m "refactor(ad-editor): AD4.R-7 image schema + scene RadiusControls derive live

The alt-text committed/draft/seen triple and the radius scene-lane
committed snapshot (A27) are retired: fields are self-drafting
projections of live values, the dirty check compares against the
document itself, and the derived 'all' arrives from hydrate instead of
a component mirror. Web branch of RadiusControls untouched."
```

---

### Task 8: Retire the `inspectorGeneration` remount machinery

**Files:**
- Modify: `apps/frontend/src/features/design-editor/hooks/use-scene-editing-session.ts:106-139,517-545`
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx:181-197`

**Interfaces:**
- Consumes: Tasks 4–7 (every ad field derives live — the remount has nothing left to resynchronize).
- Produces: `useSceneEditingSession` no longer returns `inspectorGeneration`; `onWriteReload` is a bare nonce bump; the ad inspector's key is `sceneSession.primaryNodeId ?? "canvas"` — selection changes remain the only remount, exactly the web precedent and contract §4's strongest form.

- [ ] **Step 1: Implement.**
  - Session: delete `reloadPendingRef`, `inspectorGeneration`, the bump inside `onSceneChange` (`:133-137`), and the return-object field + its doc comment; `onWriteReload` becomes `useCallback(() => setReloadNonce((nonce) => nonce + 1), [])`. Replace the deleted comment with one line: "AD4.R: a reloaded scene reaches the panel by derivation — the fields read live hydrated state — so no remount escort is needed."
  - `editor-surface.tsx`: key becomes `key={sceneSession.primaryNodeId ?? "canvas"}`; rewrite the key comment to state the new rule ("Keyed on the SELECTED NODE only. Values need no remount to resynchronize — every bound field derives from live hydrated state (AD4.R); remounting resets UI facts (open sections, drafts), which is right exactly when the selection changes.").
- [ ] **Step 2: Full gate** (a `tsc` error anywhere `inspectorGeneration` was consumed is the checklist of stragglers).
- [ ] **Step 3: Browser proof — the CAS-conflict walk (the D10 posture under the new model):**
  1. Two tabs on the same ad. Tab B commits a radius change. In tab A, commit a conflicting edit → the D10 note "Document moved on — reloaded." appears AND every field states the server's post-reload values — **without** the panel remounting (verify: an open color-picker tab / open sections survive; before this task the generation bump destroyed them).
  2. Undo, then redo, via the action menu → fields track the server document through each reload.
  3. Mid-typing reload: focus the alt-text box, type half a description, trigger tab B's write → the reload note appears, the **focused draft survives** (the user's active edit is the one legitimate local truth), and blur commits it against the reloaded document (or reveals the reloaded value if the commit is refused as stale — either way, no lie).
- [ ] **Step 4: Restore; commit.**

```bash
git add src/features/design-editor/hooks/use-scene-editing-session.ts src/features/chat-shell/components/editor-surface.tsx
git commit -m "refactor(ad-editor): AD4.R-8 retire the inspectorGeneration remount

Live derivation makes the reload-arrival remount redundant: a reloaded
scene reaches every unfocused field by re-render, the D10 note and the
panel now agree by construction, and the only remount left is the
selection change — contract §4 in its strongest form."
```

---

### Task 9: Regression battery, records, and slice close

**Files:**
- Modify: `docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md` (the Phase AD4 lane-discipline preamble, `:663-665`)
- Create: `_memory/2026-08-22-ad4r-mvp-state-model.md`

- [ ] **Step 1: Full-suite + root gates.** `cd apps/frontend && npm run design-system:build && npm test && npm run lint && npm run build`, then root `make check`. Expected: frontend fully green; root green except the documented pre-existing pytest reds.
- [ ] **Step 2: The consolidated browser sweep** — one sitting, against the real stack, document JSON checked at every step; these eight are the distilled AD4 defect families and become Lane B's regression net:
  1. **Sibling write:** preset resize updates the Custom W/H boxes; Replace-image updates the alt-text box.
  2. **Refused write:** locked node — select, toggle, color, radius, alt text all keep stating the document.
  3. **No-op re-type:** committing a field's current value writes nothing.
  4. **Burst intent:** typing a multi-digit number commits one version.
  5. **Three surfaces:** solid/gradient walk — select, swatch, artboard never disagree.
  6. **Server reload:** CAS conflict and undo/redo re-derive without remount; focused draft survives.
  7. **Token policy:** brand pick shows token + writes binding; hex detaches; both display from the document.
  8. **AI suite unchanged:** generate/edit/remove-background/candidate review still behave per AD4.A (staged candidate outlives reloads; refused Accept changes nothing the panel holds).
  Restore the seeded document and audit it node-by-node (page, root fill, hero asset, fit, corners 32/32/96/32, lock, headline token fill/size/weight/alignment).
- [ ] **Step 3: Record in the parent plan.** In the Phase AD4 preamble (after the lane-discipline paragraph) insert:

```markdown
> **AD4.R (2026-08-22, founder-ordered) landed between Lane A and Lane B** —
> `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`. The ad
> inspector now runs the MVP state model: bound controls derive from live
> hydrated state (`liveHydration`), typed fields are self-drafting
> (`onCommitValue`), the accepted scene mirrors up synchronously, and the
> `inspectorGeneration` remount is retired. **Binding rules for Lanes B–E:**
> bind every new row as `value={state.x}` + dispatch-only commit (never a
> local copy, never a post-commit mirror, never a mount-seeded snapshot);
> typed fields use `onCommitValue`; UI-only view choices (a "Custom" style
> selection) are the only schema-local state. The A27/A26/A28-style mirror
> patterns are RETIRED — do not reintroduce them in new rows.
```

- [ ] **Step 4: `_memory` close-out** (`_memory/2026-08-22-ad4r-mvp-state-model.md`): what changed and why (the founder ruling), the rulings-superseded table (copy from this plan's §Design record), the disclosed commit-model change, the verification evidence (gate results + the eight-scenario sweep), and **two recorded follow-ups**: (a) **web-lane migration** — the controller's mount mode is now legacy; the web inspector has the same latent defect class (browser-proven during AD4: the W4.2 radius resync, the alt-text overwrite, node-id-only guards), but its writes are async HTTP, so its migration needs either optimistic hydration or a draft-until-arrival rule before `liveHydration` can flip there — it is NOT a mechanical copy of AD4.R; (b) **G-H disabled treatment** — Task 10, pending the founder ruling.
- [ ] **Step 5: Commit.**

```bash
git add docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md _memory/2026-08-22-ad4r-mvp-state-model.md
git commit -m "docs(ad-editor): AD4.R close — MVP state model live on the ad lane

Records the corrective slice in the AD4 preamble with the binding
rules Lanes B-E must follow, and the two follow-ups: the web lane's
own migration (async transport needs its own draft rule) and the G-H
disabled-treatment gate."
```

---

### Task 10 (GATED on G-H — skip until the founder rules): `disabled={locked}` at the source

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx` (`InspectorInput`, `InspectorSelect`, `ColorControl`, `RadiusControls` — a `disabled?: boolean` prop each), `image-inspector.tsx` (pass `disabled={locked}` per control)

This closes the prevent-vs-refuse family the MVP closes with `disabled={selectedNode.locked}` (`RawStyleSection.tsx`, throughout). It is **presentation** — the field primitives have no `disabled` prop and the shell has exactly one authored `:disabled` treatment — so it ships only after the founder approves the look on real screenshots (the G-D precedent: propose from the browser, founder picks).

- [ ] **Step 1:** Produce the mockups: the image schema on a locked node with the proposed treatment (the `.sharePrimaryButtonWide:disabled` opacity applied to fields via one new modifier class — this is founder-ordered chrome if approved, the §2-delta precedent). Present; wait for the ruling.
- [ ] **Step 2 (post-ruling):** Add the `disabled` prop to the four primitives (native `disabled` attribute + the approved class; no behavior change when absent); pass `disabled={locked}` at every bound ad control; keep the dispatch-side `locked` guards (belt and suspenders, the adapter's refusal remains the authority).
- [ ] **Step 3:** Browser proof (locked node: controls visibly disabled, nothing dispatches; unlocked: all live), gate, commit: `feat(ad-editor): AD4.R-10 locked controls disable at the source (G-H ruled)`.

---

## Execution order & review notes

```
T1 (sync mirror) ─► T2 (controller mode) ─► T3 (draft input) ─► T4 (flag flip) ─► T5 ─► T6 ─► T7 ─► T8 ─► T9
                                                                                                        T10 (G-H, any time after T4)
```

- T1–T3 are individually inert/safe and independently revertible; T4 is the behavioral pivot and the diff a reviewer should read hardest; T5–T7 are deletions whose safety T4 already proved; T8 depends on all of T4–T7.
- Every task: fresh Opus implementer, reviewer on the diff (constraints block: "hunt for a control that still records a document value locally"), browser proof driven by the orchestrator, scoped re-review of every fix round — the AD4 regime unchanged.
- **The key sentence for every implementer and reviewer:** *keep three physical layers, but only the accepted scene owns document values — the canvas and the inspector are both projections of it, and a local copy of a document value is a defect even when it currently displays the right number.*
