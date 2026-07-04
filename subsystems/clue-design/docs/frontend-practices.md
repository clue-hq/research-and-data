# Frontend Practices — Editor Shell (`apps/editor`)

**Status: canonical.** Standing rules for anyone (agent or human) touching
`apps/editor/src`. Sourced from the Phase 1 sweeper audit, verified and
triaged on 2026-07-04. If this doc conflicts with an older phase doc, this
doc wins. If a rule changes, change it here — don't fork guidance elsewhere.

---

## 1. Architecture

```
components/          React shell — layout, panels, field binding. No policy.
  canvas/            CanvasKit = product surface. Konva = test-only fallback.
engine/              Workflow + engine layer — the canonical abstractions:
                     operations.ts / structuredEdits.ts  (operation builders)
                     editQueue.ts   (persistence + base_version reconcile)
                     wasmEngine.ts  (WASM handshake, optimistic scene)
                     gestureMachine.ts, canvaskitGestures.ts  (gestures)
crates/lumen-wasm    Rust engine in WASM; owns the local scene.
```

**There is exactly one scene-mutation path:**

> UI emits operations or structured edits (via the builders) → engine
> applies them → `editQueue` handles history and persistence.

- Never mutate scene state directly from a component.
- Never persist around `editQueue`.
- Never build operation payloads inline in JSX — use the builders.
- Never fold `editQueue`, `wasmEngine`, or the gesture modules into UI code.
  That boundary is the best part of this codebase. Keep it.

---

## 2. Rules

1. **All edits go through the one mutation path.** No exceptions for
   "small" edits.

2. **Visual components don't know workflow policy.** Accept/Reject gating,
   agent turns, the message queue, export/preflight, undo/redo — all of that
   lives in hooks/controllers. Components bind fields and fire callbacks;
   they never decide whether an action is allowed.

3. **No new raw style values.** `styles.css` opens with the design-token
   layer (`--chrome-*`, `--panel-*`, `--teal-*`, `--action-*`, `--radius-*`,
   `--shadow-*`) — the single place the Moda restyle edits. New rules use
   `var(...)`; a raw color/radius is allowed only for a genuine one-off,
   and never a near-duplicate of an existing token's value.

4. **CanvasKit is the only product canvas.** Konva exists solely because
   jsdom can't run CanvasKit — the unit suite renders through it with
   `NEXT_PUBLIC_LUMEN_CANVASKIT=0`. So: never judge UX or layout by Konva
   output, and never remove Konva until a browser-test harness replaces the
   unit coverage it carries.

5. **Browser-verify every shell-flow change.** The unit suite has a proven
   blind spot: 377 tests stayed green while persistence was broken in every
   real browser. If your change touches persistence, the WASM handshake,
   agent turns, or the shell — verify in a real browser: select, edit text,
   drag, agent preview, accept, reject, reload-and-persist, export panel.
   Save evidence in `.context/<increment>/browser-e2e/`.

6. **No ad hoc logging.** No scattered `console.log` traces. If a feature
   needs visibility, use one small semantic event logger with named events.

7. **Config lives in one place.** The API base URL fallback is currently
   copy-pasted 12×; centralizing it into `editorConfig.ts` is scheduled.
   Never add another inline copy — new config reads go through the central
   module (create it if it doesn't exist yet).

8. **Wrap browser APIs — never store them bare.** A bare `fetch` stored as
   a class field throws "Illegal invocation" in real browsers but passes in
   jsdom (see `engine/editQueue.ts:59`). Wrap it:
   `(input, init) => fetch(input, init)`. Same for any Window-bound API.

9. **Comments state invariants, not history.** Good: "engine owns local
   scene application." Bad: "added in Phase 2a." No new Phase/Wave/Track
   comments; history belongs in `docs/` and `.context/`. Clean old ones
   only when you're already touching the file.

10. **Refactor in small verified slices.** Hook extraction is not
    automatically behavior-preserving (effect ordering, stale closures, ref
    identity), and per rule 5 the unit suite won't catch it. Verbatim code
    moves, one hook per commit, browser-verified per slice. No big-bang
    refactors.

---

## 3. Known debt — fixes are scheduled, don't freelance

Each item below rides a specific increment. **Don't fix them "while you're
in there."**

| Debt | When it gets fixed |
|---|---|
| ~~API base URL copy-pasted 12×~~ | **DONE 2a.5** → `engine/editorConfig.ts` |
| ~~Agent-turn state inside `EditorApp`~~ | **DONE 2a.5** → `hooks/useAgentTurn` (2b then rewrote it in place, as planned) |
| Undo/redo + documentId-adoption logic in `EditorApp` | **2d** — not earlier; adoption has three sites and a false-divergence trap |
| Drop the `selected_node_id` back-compat field (2c kept it one release) | post-Phase-2 chore (coordinated API + editor change) |
| ~~`EditorApp` shell split (~2,100 lines, ~25 `useState`)~~ | **DONE pre-restyle hygiene** → 1,445 lines / 5 core `useState`; clusters in `hooks/useWorkspaceChrome`, `useBrandChecks`, `useExportPreflight`; chrome in `components/EditorChrome`; pure helpers in `engine/pageDuplication`, `engine/editorKeyboard`, `engine/operationLabels` |
| ~~CSS token layer (`styles.css`, ~2,200 lines)~~ | **DONE pre-restyle hygiene** → `:root` token block (chrome/panel/teal/action/radius/shadow), 302 sites tokenized |
| ~~`InspectorPanel` split into sections (1,715 lines)~~ | **DONE pre-restyle hygiene** → ~145-line orchestrator + `components/inspector/*` sections |
| Old phase comments | opportunistic only |

Until then, **don't extend the debt**: no new state concerns in `EditorApp`,
no new inline forms in `InspectorPanel`, no 13th config copy. New workflow
state starts life in a hook, even if neighboring code doesn't.

---

## 4. Known traps

- **Canvas renders but can't select/edit** → the WASM bundle drifted from
  the API build and the editor silently fell back to server-only mode.
  Check the canvas banner first, then rebuild: `scripts/build_wasm_core.sh`.
  (The `predev` preflight guards this.)
- **jsdom green ≠ browser works** — especially around `fetch`, WASM,
  CanvasKit, and timing. See rule 5.
- **documentId adoption has three sites** (create / load / reconcile).
  Missing one causes false reconcile-divergence diagnostics. Don't touch it
  outside its scheduled increment.
- **Preview text layout ≠ server text layout.** The WASM core uses heuristic
  text measurement (no Skia on wasm32); the server is authority. Small
  divergence is expected — don't "fix" it by forking layout logic in JS.
- **Run the suite from `apps/editor`, never the repo root.** A bare
  `npx vitest` from the root finds no local install, silently uses an
  npx-cached vitest with NO project config (no jsdom — `environment ~0ms`
  in the summary — and no JSX transform), and "fails" every `.tsx` file
  with `Unexpected JSX expression` pointing at valid code. This burned
  cycles in 2b and 2c masquerading as a transform-cache flake. A root
  `vitest.config.ts` guard now turns it into one clear error; the fix is
  always `cd apps/editor && npm test`.

---

## 5. Definition of done

1. Mutations use the canonical path; no policy in visual components.
2. No new raw style values, inline config, or phase comments.
3. `npx vitest run` green in `apps/editor`.
4. Browser-verified if the change touches any shell flow (rule 5).
5. Debt table (§3) untouched — unless your change *is* the scheduled fix,
   in which case update the table.
