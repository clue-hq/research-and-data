# Site editor sync fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The site editor never saves a stale or hidden copy of a site over the real one: the server is the truth, the app holds the only working copy, and the editor frame (with Puck inside) only displays it and proposes edits.

**Architecture:** The app keeps the working copy in a small store with a revision counter that moves on every change the app makes itself (a load adopted, a dock edit, an image placed, a refused save reverted). Every such change is pushed to the frame with its revision; every canvas edit the frame proposes is stamped with the revision it started from, and a proposal over an older revision is refused. Puck's own undo history, keyboard shortcuts, load-time refill and index-based selection are switched off or overridden in the frame. Loads older than what the app has already written are ignored; saves and history steps run in the order asked; the server reports the version each write produced.

**Tech Stack:** TypeScript (React 19, Next.js app, `@puckeditor/core` 0.23, zod), `node:test` + `tsx` + jsdom for unit and hook tests, Playwright via pytest for the real-browser editor harness (`tests/site_editor/`), Python/FastAPI for the design API route fix.

**Spec:** the approved design in this conversation (founder, 2026-10-14) and the findings it closes, recorded in `docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md` §4.1 and `docs/superpowers/verification/2026-10-14-wave2-contract-review-findings.md` (K1-4, K3-3, K3-5). Raw probes that reproduce each finding: `.superpowers/review/2026-10-13-wave2/reports/{S1-site-kit,S2a-site-editor-package,S2b-site-editor-app,S3-design-api-sites}-probes/`.

## Global Constraints

- The server is the only truth for a site; the app is the only side that saves (Contract 6; ruling "the app holds the site JSON and is the only side that saves").
- Decision D2 stands: agent sections run in ONE editor frame per workspace. No per-section isolation.
- Undo is the server's stack. Puck's in-frame history is never the source of undo (Contract 6 `shortcut`).
- An edit outside edit mode, or under the agent-run lock, is never saved (Lane C Review Focus 5).
- This repo's react-hooks lint rules: no synchronous `setState` inside an effect body, no ref reads during render. Use the adjust-state-on-prop-change pattern or external stores.
- The frontend gate is `npm run design-system:build && npm run lint && npm run build` in `apps/frontend`, with trenton's dev stack frontend stopped only if a build conflicts (it builds into `.next`; the dev server uses `.next/dev`).
- Python tests run ONLY through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <one file>` (test DB `clue_trenton_wave1`, keys blanked).
- Browser harness tests run with `CLUE_SITE_EDITOR_BROWSER=1` through the same script, one file at a time; they use the BUILT editor, so run `npm run build -w @clue/site-editor` from `apps/frontend` first (trenton's `dev.ts` watcher also rebuilds `dist/`).
- No Claude/AI attribution in commits. Commit locally only; never push.
- The uncommitted 3-line debug log in `subsystems/clue-design/apps/api/lumen_api/main.py` near line 9666 belongs to another session: never stage it. Stage `main.py` by hunk (`git diff` → filtered patch → `git apply --cached`).

## Review Focus

1. **The marketer is mid-typing on the canvas when an outside change arrives** (a dock edit, an agent checkpoint, a reload that brings a different copy). Expected: a dock edit keeps their typing (it is a patch); a different whole copy wins and their unsent typing is dropped, exactly once, never silently re-sent later. Pinned in Task 8 (frame) and Task 11 (scenario).
2. **Two proposals in a row before the app answers** (the frame flushes, the marketer keeps typing, the frame flushes again). Expected: both are accepted; the second carries the same base revision as the first. Pinned in Task 9.
3. **A save refused for any reason** (422, 409 moved on, 409 agent run) **while more edits are queued.** Expected: the queue is cleared, the app reloads, the canvas shows the server's copy, nothing refused is ever sent again. Pinned in Tasks 2 and 9.
4. **Coming back to a site tab after another site or a web/ad tab.** Expected: nothing is shown or saved from the old load; the canvas waits for a fresh read. Pinned in Task 9.
5. **German and Dvorak keyboards, Windows Ctrl+Z / Ctrl+Y, and ⌘Z inside an `<input>` an agent section draws.** Expected: Puck's history never runs; in editable text the browser's own text undo works; elsewhere the server's undo runs. Pinned in Task 4.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `apps/frontend/src/features/site-editor/hooks/site-save-controller.ts` | Ordered queue of saves and history steps; attach/detach lifetime; reload-when-idle | 1, 2 |
| `apps/frontend/src/features/site-editor/hooks/use-site-saves.ts` | React mirror of the controller; StrictMode-safe lifetime | 1 |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | Site write routes answer with the version the write produced | 3 |
| `apps/frontend/packages/site-editor/src/client/keys.ts` (new) | One pure decision for every history keystroke in the frame | 4 |
| `apps/frontend/packages/site-editor/src/client/editor-app.tsx` | Uses `keys.ts`; PuckBridge resets Puck history and re-points selection on every outside page | 4, 5 |
| `apps/frontend/packages/site-editor/src/client/frame-controller.ts` | Revisions; buffer while loading; selection refresh | 5, 8 |
| `apps/frontend/packages/site-kit/src/config.tsx`, `src/editor/clone-editor.tsx` | No load-time refill; blur saves only real changes; redraw when HTML is unchanged | 6 |
| `apps/frontend/packages/site-kit/src/editor-protocol.ts` | Protocol v2: `rev` on app→frame site messages, `baseRev` on `changed` | 7 |
| `apps/frontend/src/features/site-editor/model/site-working-copy.ts` (new) | The app's working copy and revision counter; proposal and load decisions | 9 |
| `apps/frontend/src/features/site-editor/model/site-frame-sync.ts` | `frameSyncFor` by revision | 9 |
| `apps/frontend/src/features/site-editor/hooks/use-site-document.ts` | A load belongs to one visit of a document (no stale copy on return) | 9 |
| `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` | Wires the working copy, the decisions and the protocol | 9 |
| `apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.ts`, `chat-shell/components/editor-surface.tsx` | Standalone route reloads only for changes the session did not make | 10 |
| `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.scenario.test.ts` (new) | The core promise end to end: real session + real FrameController over an in-memory bridge | 11 |

---

### Task 1: The save controller survives React StrictMode (S2b-2)

**Files:**
- Modify: `apps/frontend/src/features/site-editor/hooks/site-save-controller.ts` (add `attach()`; `dispose()` becomes `detach()` semantics)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-saves.ts:48-61`
- Test: `apps/frontend/src/features/site-editor/hooks/use-site-saves.test.ts` (new)

**Interfaces:**
- Produces: `SiteSaveController.attach(): void` (marks the controller live), `SiteSaveController.dispose(): void` (marks it dead; idempotent; `attach()` revives it). `useSiteSaves` attaches in an effect and disposes in its cleanup.

- [ ] **Step 1: Write the failing test** (port of `S2b-site-editor-app-probes/strict-mode-saves.tsx`)

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { fixtureSiteRepository, SITE_FIXTURE_DOCUMENT_ID } from "../data/site.repository";
import { useSiteSaves } from "./use-site-saves";

function mountDom() {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost/" });
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  return dom;
}

for (const strict of [false, true]) {
  test(`a save reaches the server${strict ? " under StrictMode" : ""}`, async () => {
    const dom = mountDom();
    const base = fixtureSiteRepository();
    const saved: number[] = [];
    const repository = { ...base, save: async (id: string, request: Parameters<typeof base.save>[1]) => { saved.push(request.baseVersion); return base.save(id, request); } };
    const seen: ReturnType<typeof useSiteSaves>[] = [];
    function Probe() {
      seen.push(useSiteSaves({ documentId: SITE_FIXTURE_DOCUMENT_ID, lockNote: "locked", onReload: () => undefined, repository }));
      return null;
    }
    const root = createRoot(dom.window.document.getElementById("root")!);
    await act(async () => root.render(strict ? createElement(StrictMode, null, createElement(Probe)) : createElement(Probe)));
    const loaded = await base.get(SITE_FIXTURE_DOCUMENT_ID);
    await act(async () => seen.at(-1)!.adopt(loaded));
    await act(async () => seen.at(-1)!.save({ ...loaded.site, title: "Edited title" }));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    assert.deepEqual(saved, [loaded.version]);
    assert.equal((await base.get(SITE_FIXTURE_DOCUMENT_ID)).site.title, "Edited title");
    assert.equal(seen.at(-1)!.baseVersion, loaded.version + 1);
    await act(async () => root.unmount());
  });
}
```

- [ ] **Step 2: Run it to see the StrictMode case fail**

Run: `cd apps/frontend && npx tsx --test src/features/site-editor/hooks/use-site-saves.test.ts`
Expected: the non-strict test passes; the StrictMode test FAILS (`saved` is `[]`).

- [ ] **Step 3: Implement**

In `site-save-controller.ts`, replace the `dispose` method with:

```ts
  /** Mark the controller live. React's StrictMode runs an effect's cleanup and then the effect
   * again on the same render's objects, so the lifetime is attach/dispose, not create/dispose. */
  attach(): void {
    this.disposed = false;
  }

  dispose(): void {
    this.disposed = true;
  }
```

In `use-site-saves.ts`, replace `useEffect(() => () => controller?.dispose(), [controller]);` with:

```ts
  useEffect(() => {
    controller?.attach();
    return () => controller?.dispose();
  }, [controller]);
```

- [ ] **Step 4: Run the test and the controller tests**

Run: `npx tsx --test src/features/site-editor/hooks/use-site-saves.test.ts src/features/site-editor/hooks/site-save-controller.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/site-editor/hooks/site-save-controller.ts apps/frontend/src/features/site-editor/hooks/use-site-saves.ts apps/frontend/src/features/site-editor/hooks/use-site-saves.test.ts
git commit -m "site editor: the save controller survives React StrictMode (every dev-stack site save did nothing)"
```

---

### Task 2: Saves and history steps run in the order asked; a deferred reload waits for idle (S2b-4)

**Files:**
- Modify: `apps/frontend/src/features/site-editor/hooks/site-save-controller.ts`
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-saves.ts` (expose `requestReloadWhenIdle` and `isIdle`)
- Test: `apps/frontend/src/features/site-editor/hooks/site-save-controller.test.ts` (append)

**Interfaces:**
- Produces: `SiteSaveController.isIdle(): boolean` (nothing in flight, nothing queued); `SiteSaveController.requestReloadWhenIdle(): void` (calls `onReload` now if idle, else once when the queue drains without a refusal). `SiteSaves.isIdle(): boolean` and `SiteSaves.requestReloadWhenIdle(): void` mirror them.
- Queue rule: one FIFO of operations; a save queued directly after another queued save replaces it (the newest whole site contains the other); a refusal clears the queue (unchanged policy).

- [ ] **Step 1: Write the failing tests** (append; reuse the file's `harness`, `site`, `deferred` helpers — read the top of the file for their exact shape: `harness()` returns `{ controller, calls, pending, states, reloads }`; if a name differs, use the file's own)

```ts
test("two undos asked during a save both run, after it, in order", async () => {
  const h = harness();
  h.controller.save(site("First"));
  h.controller.undo();
  h.controller.undo();
  h.pending[0].resolve({ version: 2 });
  await Promise.resolve(); await Promise.resolve();
  h.pending[1].resolve({ version: 3 });
  await Promise.resolve(); await Promise.resolve();
  h.pending[2].resolve({ version: 4 });
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls.map((call) => call.op), ["save", "undo", "undo"]);
});

test("an undo asked before a later edit runs before that edit is saved", async () => {
  const h = harness();
  h.controller.save(site("Typo heading"));
  h.controller.undo();
  h.controller.save(site("Typo heading, more"));
  for (let i = 0; i < 3; i += 1) {
    h.pending[i].resolve({ version: 2 + i });
    await Promise.resolve(); await Promise.resolve();
  }
  assert.deepEqual(h.calls.map((call) => `${call.op}${call.heading ? ` ${call.heading}` : ""}`), ["save Typo heading", "undo", "save Typo heading, more"]);
});

test("back-to-back queued saves merge into the newest", async () => {
  const h = harness();
  h.controller.save(site("A"));
  h.controller.save(site("B"));
  h.controller.save(site("C"));
  h.pending[0].resolve({ version: 2 });
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(h.calls.map((call) => call.heading), ["A", "C"]);
});

test("a reload requested while busy fires once the queue drains", async () => {
  const h = harness();
  h.controller.save(site("A"));
  assert.equal(h.controller.isIdle(), false);
  h.controller.requestReloadWhenIdle();
  assert.equal(h.reloads(), 0);
  h.pending[0].resolve({ version: 2 });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(h.controller.isIdle(), true);
  assert.equal(h.reloads(), 1);
  h.controller.requestReloadWhenIdle();
  assert.equal(h.reloads(), 2);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx tsx --test src/features/site-editor/hooks/site-save-controller.test.ts`
Expected: the first two FAIL (single-slot queue), the last FAILS (`isIdle` is not a function).

- [ ] **Step 3: Implement**

Replace `pendingSave`/`pendingStep` with one queue:

```ts
type QueuedOperation = { kind: "save"; site: SiteDocument; intent?: string } | { kind: "step"; step: HistoryStep };

  private queue: QueuedOperation[] = [];
  private reloadWhenIdle = false;

  isIdle(): boolean {
    return !this.inFlight && this.queue.length === 0;
  }

  requestReloadWhenIdle(): void {
    if (this.isIdle()) {
      this.deps.onReload();
      return;
    }
    this.reloadWhenIdle = true;
  }

  save(site: SiteDocument, intent?: string): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      const last = this.queue.at(-1);
      if (last?.kind === "save") this.queue[this.queue.length - 1] = { kind: "save", site, intent };
      else this.queue.push({ kind: "save", site, intent });
      return;
    }
    void this.runSave(site, intent);
  }

  private step(step: HistoryStep): void {
    if (this.disposed || this.state.baseVersion === null) return;
    if (this.inFlight) {
      this.queue.push({ kind: "step", step });
      return;
    }
    void this.runStep(step);
  }

  private finish(): void {
    this.inFlight = false;
    const next = this.queue.shift();
    if (next?.kind === "save") {
      void this.runSave(next.site, next.intent);
      return;
    }
    if (next?.kind === "step") {
      void this.runStep(next.step);
      return;
    }
    this.update({ busy: false });
    if (this.reloadWhenIdle) {
      this.reloadWhenIdle = false;
      this.deps.onReload();
    }
  }

  private abandon(): void {
    this.inFlight = false;
    this.queue = [];
    // A refusal reloads on its own (refused()); the deferred reload is satisfied by it.
    this.reloadWhenIdle = false;
  }
```

Note: `runStep` calls `this.finish()` then `this.deps.onReload()`; keep that order (the step's own reload is separate from a deferred one). If the harness lacks a `reloads()` counter, add one to it: count calls of the `onReload` dep.

In `use-site-saves.ts`, add to `SiteSaves` and `actions`:

```ts
  isIdle: () => boolean;
  requestReloadWhenIdle: () => void;
// actions:
      isIdle: () => controller?.isIdle() ?? true,
      requestReloadWhenIdle: () => controller?.requestReloadWhenIdle(),
```

- [ ] **Step 4: Run all controller tests**

Run: `npx tsx --test src/features/site-editor/hooks/site-save-controller.test.ts src/features/site-editor/hooks/use-site-saves.test.ts`
Expected: all pass (the existing "latest step wins" test, if present, must be updated to the new ordered rule: rewrite its expectation to the arrival order and say so in the commit).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/site-editor/hooks/site-save-controller.ts apps/frontend/src/features/site-editor/hooks/site-save-controller.test.ts apps/frontend/src/features/site-editor/hooks/use-site-saves.ts
git commit -m "site editor: saves and history steps run in the order asked; a reload can wait for the queue to drain"
```

---

### Task 3: Site write routes answer with the version the write produced (S3-3)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`_write_site`, `put_site_document`, `_step_site`, `restore_site_version`)
- Test: `subsystems/clue-design/apps/api/tests/test_site_write_routes.py` (append), adapted from `.superpowers/review/2026-10-13-wave2/reports/S3-design-api-sites-probes/test_probe_s3_version_report.py`

**Interfaces:**
- Produces: `_write_site(...) -> int` (the produced `current_version` from the tool's references). Route bodies keep their shape: `{"schema_version": 1, "document": {"id", "current_version", "doc_kind": "site"}}`; `current_version` is now the produced one.

- [ ] **Step 1: Write the failing test.** Copy the probe's fixtures and its race injection (it monkeypatches the repository so a rename commits between the write and the response). Assert the route reports the version the save produced and that a second save from that base is refused 409:

```python
def test_a_save_reports_the_version_it_produced_not_a_later_one(...):  # use the probe's fixtures verbatim
    # ... probe setup: a site at version 0; the injected rename commits version 2 right after the save's commit ...
    response = client.put(f"/documents/{doc_id}/site", json={"site": site, "base_version": 0})
    assert response.status_code == 200
    assert response.json()["document"]["current_version"] == 1
    stale = client.put(f"/documents/{doc_id}/site", json={"site": site, "base_version": 1})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "edits.base_version_mismatch"
```

Read the probe file first and keep its exact fixture names; the step's contract is the two assertions blocks above.

- [ ] **Step 2: Run it to see it fail**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_write_routes.py -k produced`
Expected: FAIL (`current_version == 2`).

- [ ] **Step 3: Implement.** `_write_site` returns `int(refs["current_version"])` (the tool's `DocumentStateRef`); `put_site_document` and `restore_site_version` answer `{"id": document_id, "current_version": produced, "doc_kind": "site"}`; `_step_site` answers with `int(refs["current_version"])`. Delete `_site_document_ref` if nothing else uses it (`grep -n "_site_document_ref" main.py`).

- [ ] **Step 4: Run the whole file**

Run: `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_write_routes.py`
Expected: all pass.

- [ ] **Step 5: Commit by hunk** (never the other session's debug log near line 9666):

```bash
git diff subsystems/clue-design/apps/api/lumen_api/main.py > /tmp/main.full.patch   # scratchpad path in practice
# keep only this task's hunks in a filtered patch, then:
git apply --cached <filtered.patch>
git add subsystems/clue-design/apps/api/tests/test_site_write_routes.py
git commit -m "design API: site writes answer with the version they produced, never a re-read"
```

---

### Task 4: In the frame, Puck's history never runs (S2a-1, keyboard part)

**Files:**
- Create: `apps/frontend/packages/site-editor/src/client/keys.ts`
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx:64-71`
- Test: `apps/frontend/packages/site-editor/test/keys.test.ts` (new); browser regression `tests/site_editor/test_editor_history_keys.py` (new, from `S2a-site-editor-package-probes/test_s2a_puck_history.py`)

**Interfaces:**
- Produces: `frameKeyAction(event: { key: string; code: string; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; target: unknown }): { stop: boolean; preventDefault: boolean; send: "undo" | "redo" | null }`.

Rule (from the design): with ⌘ or Ctrl held and either the character (`z`/`y`) or the physical key (`KeyZ`/`KeyY`) of a history shortcut —
- in editable text (contentEditable, INPUT, TEXTAREA, SELECT): `{ stop: true, preventDefault: false, send: null }` (the browser's own text undo runs; Puck never sees it);
- elsewhere, when the CHARACTER is z/y: `{ stop: true, preventDefault: true, send: undo|redo }`;
- elsewhere, when only the physical key matches (Dvorak ⌘; on the KeyZ key): `{ stop: true, preventDefault: false, send: null }`.
- ⌘I / Ctrl+I keeps today's swallow: `{ stop: true, preventDefault: true, send: null }`.
- Anything else: `{ stop: false, preventDefault: false, send: null }`.

- [ ] **Step 1: Write the failing unit test**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { frameKeyAction } from "../src/client/keys";

const text = { isContentEditable: true, tagName: "H1" };
const body = { isContentEditable: false, tagName: "BODY" };
const input = { isContentEditable: false, tagName: "INPUT" };
const key = (over: Partial<Parameters<typeof frameKeyAction>[0]>) =>
  frameKeyAction({ key: "z", code: "KeyZ", metaKey: true, ctrlKey: false, shiftKey: false, target: body, ...over });

test("⌘Z outside text is the server's undo; ⇧⌘Z and ⌘Y are redo", () => {
  assert.deepEqual(key({}), { stop: true, preventDefault: true, send: "undo" });
  assert.deepEqual(key({ shiftKey: true }), { stop: true, preventDefault: true, send: "redo" });
  assert.deepEqual(key({ key: "y", code: "KeyY" }), { stop: true, preventDefault: true, send: "redo" });
  assert.deepEqual(key({ metaKey: false, ctrlKey: true }), { stop: true, preventDefault: true, send: "undo" });
});

test("in editable text the browser's undo runs and Puck never sees the key", () => {
  assert.deepEqual(key({ target: text }), { stop: true, preventDefault: false, send: null });
  assert.deepEqual(key({ target: input }), { stop: true, preventDefault: false, send: null });
});

test("QWERTZ: the z character on the KeyY key is undo, never Puck's redo", () => {
  assert.deepEqual(key({ code: "KeyY" }), { stop: true, preventDefault: true, send: "undo" });
});

test("Dvorak: the KeyZ key typing ';' runs nothing and Puck never sees it", () => {
  assert.deepEqual(key({ key: ";" }), { stop: true, preventDefault: false, send: null });
});

test("⌘I is swallowed; plain keys and other shortcuts pass", () => {
  assert.deepEqual(key({ key: "i", code: "KeyI" }), { stop: true, preventDefault: true, send: null });
  assert.deepEqual(key({ metaKey: false }), { stop: false, preventDefault: false, send: null });
  assert.deepEqual(key({ key: "c", code: "KeyC" }), { stop: false, preventDefault: false, send: null });
});
```

- [ ] **Step 2: Run it** — `cd apps/frontend && npx tsx --test packages/site-editor/test/keys.test.ts` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `keys.ts`**

```ts
// Every history keystroke in the frame, decided once. Puck registers its own undo/redo hotkeys on
// `document` and matches the PHYSICAL key (KeyZ/KeyY), with no editable-text check; the frame's
// capture listener on `window` runs first, so stopping the event here means Puck never sees it.
export interface FrameKeyAction {
  stop: boolean;
  preventDefault: boolean;
  send: "undo" | "redo" | null;
}

const PASS: FrameKeyAction = { stop: false, preventDefault: false, send: null };

function editable(target: unknown): boolean {
  const element = target as { isContentEditable?: boolean; tagName?: string } | null;
  return Boolean(
    element &&
      (element.isContentEditable === true || element.tagName === "INPUT" || element.tagName === "TEXTAREA" || element.tagName === "SELECT"),
  );
}

export function frameKeyAction(event: {
  key: string;
  code: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  target: unknown;
}): FrameKeyAction {
  if (!event.metaKey && !event.ctrlKey) return PASS;
  const character = event.key.toLowerCase();
  if (character === "i") return { stop: true, preventDefault: true, send: null };
  const historyCharacter = character === "z" || character === "y";
  const historyKey = event.code === "KeyZ" || event.code === "KeyY";
  if (!historyCharacter && !historyKey) return PASS;
  if (editable(event.target) || !historyCharacter) return { stop: true, preventDefault: false, send: null };
  const send = character === "y" || event.shiftKey ? "redo" : "undo";
  return { stop: true, preventDefault: true, send };
}
```

In `editor-app.tsx`, replace the `onKeyDown` body:

```ts
    const onKeyDown = (event: KeyboardEvent) => {
      const action = frameKeyAction(event);
      if (action.preventDefault) event.preventDefault();
      if (action.stop) event.stopImmediatePropagation();
      if (action.send) controller.shortcut(action.send);
    };
```

and import `frameKeyAction` from `./keys`; drop the now-unused `shortcutFor` import.

- [ ] **Step 4: Browser regression.** Copy `S2a-site-editor-package-probes/test_s2a_puck_history.py` to `tests/site_editor/test_editor_history_keys.py`. Keep its setup; flip each assertion so it pins the fixed behaviour: ⌘Z in a clone slot posts NO `changed` that rewinds the dock edit or the agent rewrite; ⌘Z outside text posts one `shortcut {undo}`; the Dvorak pair posts nothing; the brand-section contrast test stays as is. Rebuild and run:

```bash
cd apps/frontend && npm run build -w @clue/site-editor && cd ../..
CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/site_editor/test_editor_history_keys.py
```

Expected: PASS. Also run `npx tsx --test packages/site-editor/test/*.test.ts` (package suite) — all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/packages/site-editor/src/client/keys.ts apps/frontend/packages/site-editor/src/client/editor-app.tsx apps/frontend/packages/site-editor/test/keys.test.ts tests/site_editor/test_editor_history_keys.py
git commit -m "site editor frame: Puck's own undo never runs; editable text keeps the browser's undo, everything else is the server's"
```

---

### Task 5: Puck backstops: history reset and selection by id after every outside page (S2a-1 backstop, S2a-4)

**Files:**
- Modify: `apps/frontend/packages/site-editor/src/client/frame-controller.ts` (`PuckHandle.showPage` signature; `reselected`)
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx` (PuckBridge `showPage`)
- Test: `apps/frontend/packages/site-editor/test/frame-controller.test.ts` (append); browser regression `tests/site_editor/test_editor_selection_follows_section.py` (from `S2a-site-editor-package-probes/test_s2a_selection_shift.py`)

**Interfaces:**
- Produces: `PuckHandle.showPage(page: SitePage, selectedId: string | null): void`. `FrameController.reselected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void` — posts `selected` unconditionally (fresh fields and values after an outside page).

- [ ] **Step 1: Write the failing controller test**

```ts
test("an outside page keeps the selection on the same section id and asks Puck to point there", async () => {
  const h = harness();
  await h.controller.receive(init());
  h.controller.componentSelected("cta", "CtaBand", [], { heading: "Hello" });
  const calls: string[] = [];
  h.controller.attachPuck({
    select: () => undefined,
    setMode: () => undefined,
    showPage: (_page, selectedId) => calls.push(`show:${selectedId}`),
  });
  const next = SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": page("World") } });
  await h.controller.receive(appToFrame("replace_site", { site: next, rev: 2 } as never, { documentId: "doc_1", nonce: NONCE }));
  assert.deepEqual(calls, ["show:cta"]);
});
```

(Task 7 changes `replace_site`'s payload to `{site, rev}`; until then, cast as shown.)

- [ ] **Step 2: Run** — `npx tsx --test packages/site-editor/test/frame-controller.test.ts` — Expected: FAIL (`show:undefined`).

- [ ] **Step 3: Implement.** In `frame-controller.ts`, change `PuckHandle.showPage(page: SitePage): void` to `showPage(page: SitePage, selectedId: string | null): void`; every call passes `this.state.selection && this.state.selection.target !== SHELL_TARGET ? this.state.selection.componentId : null` (compute after the selection update). Add:

```ts
  /** After an outside page, PuckBridge re-describes the selected section so the dock's fields and
   * values are the new ones even when the id is unchanged. */
  reselected(componentId: string, componentType: string, fields: FieldDescription[], props: Record<string, unknown>): void {
    if (this.state.mode !== "edit") return;
    this.set({ selection: { componentId, target: this.state.route } });
    this.post("selected", { componentId, componentType, fields, props, route: this.state.route });
  }
```

In `editor-app.tsx` PuckBridge:

```ts
      showPage(page, selectedId) {
        const puck = getPuck();
        puck.dispatch({ data: page as unknown as Data, recordHistory: false, type: "setData" });
        // Puck's history must never hold a snapshot from before an outside change (S2a-1 backstop).
        const after = getPuck();
        after.history.setHistories([{ id: "outside", state: after.appState }]);
        const itemSelector = selectedId ? (after.getSelectorForId(selectedId) ?? null) : null;
        after.dispatch({ type: "setUi", ui: { itemSelector } });
        const item = selectedId ? after.getItemById(selectedId) : null;
        if (item && selectedId) {
          const props = item.props as Record<string, unknown>;
          controller.reselected(selectedId, item.type, fieldsForComponent(config, brand, item.type, props), props);
        }
      },
```

(Check `PuckApi.history.setHistories`'s element type in `node_modules/@puckeditor/core/dist/index.d.mts` around line 272 and match it; `appState` is on the Puck API object.)

- [ ] **Step 4: Browser regression and suites.** Copy `test_s2a_selection_shift.py` to `tests/site_editor/test_editor_selection_follows_section.py`, flip the assertion: after `replace_site` without `hero`, the selection messages are `[("selected", "proof")]` (the same section, re-described), never `close`. Rebuild the editor, run it with `CLUE_SITE_EDITOR_BROWSER=1`; run the package suite.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/packages/site-editor/src/client/frame-controller.ts apps/frontend/packages/site-editor/src/client/editor-app.tsx apps/frontend/packages/site-editor/test/frame-controller.test.ts tests/site_editor/test_editor_selection_follows_section.py
git commit -m "site editor frame: an outside page resets Puck's history and keeps the selection on the same section"
```

---

### Task 6: Cloned-section editing: no load-time refill, blur saves only real changes, the canvas never shows what will not publish (S1-1, S1-2, S1-4)

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/config.tsx:176-184` (delete `resolveData`)
- Modify: `apps/frontend/packages/site-kit/src/editor/clone-editor.tsx`
- Test: `apps/frontend/packages/site-kit/test/clone-editing.test.tsx` (new), adapted from `S1-site-kit-probes/resolve-cache.test.mts` and `clone-canvas.test.mts`

**Interfaces:**
- Produces: `ClonedSection` has no `resolveData`. `CloneEditor` dispatches a slot write only when the element's text changed since it was focused, and remounts its markup (a local key) when a dispatched write leaves the HTML string unchanged.

- [ ] **Step 1: Write the failing tests.** Copy both probes into one test file. Pin the fixed behaviour:
  - resolve-cache: mounting "hero" = clone A then "hero" = clone B with the agent's slots → `didChange` is `false` and the slots are exactly the agent's;
  - clone-canvas (blur): focus a `<br>` headline and blur without typing → no `setData` dispatch (count the dispatches through a stub `getPuck`);
  - clone-canvas (clear): clear a never-set slot and blur → after the re-render the canvas text equals what the published HTML shows (the seller's headline), never `""`.

- [ ] **Step 2: Run** — `cd apps/frontend/packages/site-kit && npx tsx --test test/clone-editing.test.tsx` — Expected: the three tests FAIL.

- [ ] **Step 3: Implement.**
  - `config.tsx`: delete the `resolveData` block and its comment; remove `slotDefaults` from the import if unused there (it stays exported from `clone.ts`/`index.ts`).
  - `clone-editor.tsx`: in the per-slot setup add `let atFocus = "";` and a focus listener `element.addEventListener("focus", () => { atFocus = element.innerText; })`; in `onBlur`, `if (element.innerText === atFocus) return;` before dispatching. Add `const [redraw, setRedraw] = useState(0);` and `const htmlAtBlur = useRef<string | null>(null);`; in `onBlur` (after the early return) set `htmlAtBlur.current = html` and `setCommitted((n) => n + 1)` alongside the dispatch; add:

```tsx
  const [committed, setCommitted] = useState(0);
  useLayoutEffect(() => {
    if (committed === 0 || htmlAtBlur.current === null) return;
    // The write produced the same markup (an empty or normalised slot): React will not touch the
    // DOM the marketer edited, so remount it to show exactly what will publish.
    if (htmlAtBlur.current === html) setRedraw((n) => n + 1);
    htmlAtBlur.current = null;
  }, [committed, html]);
  return <CloneMarkup key={redraw} clone={clone} html={html} ref={ref} />;
```

  Note the lint rule forbids `setState` synchronously in an effect: if `react-hooks/set-state-in-effect` flags `setRedraw`, derive instead: keep `redraw` as a ref-free value computed by the adjust-state-on-prop-change pattern — store `{ committed, html }` of the last handled commit in state and compare during render. Use whichever form the repo's lint accepts; the test is the contract.

- [ ] **Step 4: Run site-kit's suite** — `npm test -w @clue/site-kit` (from `apps/frontend`) — all pass; then the editor browser renders test: `CLUE_SITE_EDITOR_BROWSER=1 .superpowers/review/2026-10-13-wave2/pytest-keyless.sh tests/site_editor/test_editor_renders.py` after rebuilding the editor.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/packages/site-kit/src/config.tsx apps/frontend/packages/site-kit/src/editor/clone-editor.tsx apps/frontend/packages/site-kit/test/clone-editing.test.tsx
git commit -m "site-kit: cloned sections never refill on load, a click-away never rewrites a headline, and the canvas shows what will publish"
```

---

### Task 7: Editor protocol v2: revisions on site messages

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/editor-protocol.ts`
- Test: `apps/frontend/packages/site-kit/test/editor-protocol.test.ts` (append; create if absent)

**Interfaces:**
- Produces: `EDITOR_PROTOCOL_VERSION = 2`. Payloads: `init` gains `rev: number`; `replace_site` is `{ site, rev }` (the unused `version` is removed); `set_props` and `insert_asset` gain `rev`; `changed` is `{ site, baseRev }`. `Rev = z.number().int().nonnegative()`.

- [ ] **Step 1: Failing test**

```ts
test("v2: site messages carry revisions and a v1 message is refused", () => {
  const ctx = { documentId: "doc_1", nonce: "nonce-0123456789abcdef" };
  assert.equal(EDITOR_PROTOCOL_VERSION, 2);
  assert.ok(parseFrameToApp(frameToApp("changed", { site, baseRev: 3 }, ctx)));
  assert.equal(parseFrameToApp({ ...frameToApp("changed", { site, baseRev: 3 }, ctx), payload: { site } }), null);
  assert.ok(parseAppToFrame(appToFrame("replace_site", { site, rev: 4 }, ctx)));
  assert.equal(parseAppToFrame({ ...appToFrame("replace_site", { site, rev: 4 }, ctx), v: 1 }), null);
});
```

(`site` = any valid `SiteDocumentSchema` fixture already used in site-kit tests.)

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the schema changes above; fix every type error that follows (`frame-controller.ts` and `use-site-editing-session.ts` are rewritten in Tasks 8 and 9 — in this task, make them compile by passing `rev: 0`/`baseRev: 0` placeholders ONLY if the build must stay green between commits; Tasks 8 and 9 replace them in the same session).
- [ ] **Step 4: Run** site-kit's suite and `npx tsc --noEmit -p packages/site-editor` and the app type check of the touched files.
- [ ] **Step 5: Commit** — `git commit -m "editor protocol v2: revisions on every app→frame site message and on the frame's proposals"`

---

### Task 8: The frame side of revisions; nothing is dropped while sections load (K3-5)

**Files:**
- Modify: `apps/frontend/packages/site-editor/src/client/frame-controller.ts`
- Test: `apps/frontend/packages/site-editor/test/frame-controller.test.ts` (append)

**Interfaces:**
- Consumes: protocol v2 (Task 7).
- Produces: `FrameState.rev: number`. Rules:
  - `init` sets `rev` and remembers `loading = { site, rev, route }` until sections load; `replace_site`, `set_props`, `insert_asset` and `navigate` received while loading update `loading` instead of being dropped; the finished init shows `loading`.
  - `replace_site` when ready: if its site equals the frame's current site (canonical JSON) → only `rev` moves (pending typing kept); else the pending edit is cancelled, the page is shown and `rev` moves.
  - `set_props` / `insert_asset` when ready: the patch applies to the frame's current site (pending typing kept), `rev` moves.
  - `changed` posts `{ site, baseRev: this.state.rev }`.

- [ ] **Step 1: Failing tests**

```ts
test("an update that arrives while sections load is applied after the load, not dropped", async () => {
  let release!: () => void;
  const h = harness(() => new Promise((resolve) => { release = () => resolve([]); }));
  const loading = h.controller.receive(init({ rev: 1 }));
  const newer = SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": page("v5 heading") } });
  await h.controller.receive(appToFrame("replace_site", { site: newer, rev: 2 }, { documentId: "doc_1", nonce: NONCE }));
  release();
  await loading;
  assert.equal(h.controller.getState().rev, 2);
  assert.equal(String(pageFor(h.controller.getState().site!, "/")!.content[0].props.heading), "v5 heading");
});

test("proposals carry the revision they started from; a dock patch keeps pending typing", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 7 }));
  h.controller.pageEdited("/", page("typed"));
  await h.controller.receive(appToFrame("set_props", { componentId: "cta", props: { eyebrow: "dock" }, route: "/", rev: 8 }, { documentId: "doc_1", nonce: NONCE }));
  h.timers.at(-1)!();
  const changed = h.posts.find((post) => post.type === "changed")!.payload as { site: typeof site; baseRev: number };
  assert.equal(changed.baseRev, 8);
  const props = pageFor(changed.site, "/")!.content[0].props;
  assert.equal(props.heading, "typed");
  assert.equal(props.eyebrow, "dock");
});

test("a different whole copy wins over unsent typing; an identical one only moves the revision", async () => {
  const h = harness();
  await h.controller.receive(init({ rev: 1 }));
  h.controller.pageEdited("/", page("typed"));
  const same = h.controller.getState().site!;
  await h.controller.receive(appToFrame("replace_site", { site: same, rev: 2 }, { documentId: "doc_1", nonce: NONCE }));
  assert.equal(h.controller.getState().rev, 2);
  h.timers.at(-1)!();
  assert.equal(h.posts.filter((post) => post.type === "changed").length, 1);
  const other = SiteDocumentSchema.parse({ ...site, pages: { ...site.pages, "/": page("server") } });
  h.controller.pageEdited("/", page("typed again"));
  await h.controller.receive(appToFrame("replace_site", { site: other, rev: 3 }, { documentId: "doc_1", nonce: NONCE }));
  assert.equal(String(pageFor(h.controller.getState().site!, "/")!.content[0].props.heading), "server");
});
```

(Update the harness `init` helper to accept `rev`, and import `pageFor` from `@clue/site-kit/editor-site`.)

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the rules above in `frame-controller.ts`: add `rev: 0` to `INITIAL`; a private `loading: { site: SiteDocument; rev: number; route: string } | null`; `init` sets it and, on completion, reads it; the four handlers check `this.state.status === "loading" && this.loading` first; `replaceSite(site, rev)` compares `canonicalJson`; `applyOutsideEdit(site, target, rev)`; `flushChange` posts `{ site, baseRev: this.state.rev }`.
- [ ] **Step 4: Run** the package suite and `npx tsc --noEmit -p packages/site-editor`.
- [ ] **Step 5: Commit** — `git commit -m "site editor frame: revisions on every copy it shows, proposals stamped with their base, nothing dropped while sections load"`

---

### Task 9: The app's working copy; adopt only newer loads; sync by revision; a fresh read on return (K1-4, K3-3 core, S2b-3)

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-working-copy.ts`
- Modify: `apps/frontend/src/features/site-editor/model/site-frame-sync.ts`
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-document.ts`
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`
- Test: `apps/frontend/src/features/site-editor/model/site-working-copy.test.ts` (new); `site-frame-sync.test.ts` (update); `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.test.ts` (new; ports of `reload-during-save.tsx`, `tab-return-stale-load.tsx`, `upload-after-tab-switch.tsx` is out of scope — S2b-1 is a separate fix)

**Interfaces:**
- Produces (`site-working-copy.ts`):

```ts
export interface WorkingCopy { documentId: string; site: SiteDocument; rev: number }
export type ProposalVerdict = "accepted" | "stale" | "unchanged";
export type LoadDecision = "adopt" | "stale" | "defer";

/** Pure: may a load replace the working copy? */
export function loadDecision(input: { loadedVersion: number; knownVersion: number | null; idle: boolean }): LoadDecision;
// knownVersion null → "adopt"; loadedVersion < knownVersion → "stale"; !idle → "defer"; else "adopt".

export class SiteWorkingCopy {
  subscribe(listener: () => void): () => void;
  get(): WorkingCopy | null;
  /** A load the decision allowed. Returns true when the content changed (the revision moved). */
  adoptLoad(documentId: string, site: SiteDocument): boolean;
  /** A canvas edit. Accepted only when baseRev is the current revision. Frame-originated, so the
   * revision does not move (the frame already shows it). */
  propose(documentId: string, site: SiteDocument, baseRev: number): ProposalVerdict;
  /** An app-originated change (a dock edit, an image placed). Returns the new revision. */
  edit(documentId: string, site: SiteDocument): number | null;
  forget(): void;
}
```

  Revisions come from one counter per `SiteWorkingCopy` instance and never repeat, across documents.
- Produces (`site-frame-sync.ts`): `frameSyncFor({ frameReady, initKey, sentInitKey, sentRev, rev }): { kind: "init" } | { kind: "replace"; rev: number } | { kind: "none" }`.
- Produces (`use-site-document.ts`): a load is returned only for the visit it was read in. Leaving a document (to another or to none) and coming back shows `LOADING` until a fresh read lands.
- Session (`use-site-editing-session.ts`):
  - the working copy lives in a `SiteWorkingCopy` (one per hook instance, `useState(() => new SiteWorkingCopy())`), read with `useSyncExternalStore`;
  - on every new `load.loaded`, an effect runs `loadDecision({ loadedVersion, knownVersion: saves.baseVersion, idle: saves.isIdle() })`: `adopt` → `copy.adoptLoad(...)` then `saves.adopt(loaded)`; `stale` → nothing; `defer` → `saves.requestReloadWhenIdle()`;
  - when `activeDocumentId` changes, an effect calls `copy.forget()`;
  - `changed`: `copy.propose(documentId, site, baseRev)`; only `accepted` saves;
  - dock commit and image placement read the CURRENT copy from `copy.get()` (never a render-time closure), call `copy.edit(...)`, post `set_props`/`insert_asset` with the returned `rev`, set `sent.current.rev = rev`, then save;
  - the sync effect uses `frameSyncFor` by `rev`; `init` and `replace_site` carry `rev`;
  - `setSite` and `AppSite.version` are removed; `version` in the returned object is `saves.baseVersion`.

- [ ] **Step 1: Failing unit tests** for `site-working-copy.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { loadDecision, SiteWorkingCopy } from "./site-working-copy";

const site = (heading: string) =>
  ({ id: "d", title: "S", theme: {}, shell: null, agent_sections: {}, pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta", heading } }] } } }) as unknown as SiteDocument;

test("load decisions", () => {
  assert.equal(loadDecision({ loadedVersion: 3, knownVersion: null, idle: false }), "adopt");
  assert.equal(loadDecision({ loadedVersion: 4, knownVersion: 5, idle: true }), "stale");
  assert.equal(loadDecision({ loadedVersion: 5, knownVersion: 5, idle: false }), "defer");
  assert.equal(loadDecision({ loadedVersion: 5, knownVersion: 5, idle: true }), "adopt");
  assert.equal(loadDecision({ loadedVersion: 6, knownVersion: 5, idle: true }), "adopt");
});

test("an adopted load moves the revision only when the content changed", () => {
  const copy = new SiteWorkingCopy();
  assert.equal(copy.adoptLoad("d", site("A")), true);
  const first = copy.get()!.rev;
  assert.equal(copy.adoptLoad("d", site("A")), false);
  assert.equal(copy.get()!.rev, first);
  assert.equal(copy.adoptLoad("d", site("B")), true);
  assert.ok(copy.get()!.rev > first);
});

test("proposals: accepted at the current revision (twice in a row), stale after an app edit, unchanged when equal", () => {
  const copy = new SiteWorkingCopy();
  copy.adoptLoad("d", site("A"));
  const rev = copy.get()!.rev;
  assert.equal(copy.propose("d", site("A1"), rev), "accepted");
  assert.equal(copy.propose("d", site("A12"), rev), "accepted");
  assert.equal(copy.get()!.rev, rev);
  assert.equal(copy.propose("d", site("A12"), rev), "unchanged");
  const edited = copy.edit("d", site("dock"))!;
  assert.ok(edited > rev);
  assert.equal(copy.propose("d", site("late typing"), rev), "stale");
  assert.equal(copy.propose("other", site("x"), edited), "stale");
});

test("forget drops the copy; revisions never repeat across documents", () => {
  const copy = new SiteWorkingCopy();
  copy.adoptLoad("d", site("A"));
  const before = copy.get()!.rev;
  copy.forget();
  assert.equal(copy.get(), null);
  copy.adoptLoad("e", site("A"));
  assert.ok(copy.get()!.rev > before);
});
```

  Update `site-frame-sync.test.ts` to the `rev` signature (the same four cases, `sentRev`/`rev`).

  Hook tests in `use-site-editing-session.test.ts`: port `reload-during-save.tsx` (both orderings) and `tab-return-stale-load.tsx` into `node:test` form (use the jsdom setup from `use-artifact-sharing-controller.test.ts`; drive a canvas edit by calling the session's own frame-message path — see Task 11's bridge, or, until it exists, `latest().saves.save` plus the copy via the dock path). Pin:
  - get-first: the server keeps `"New headline"` after the later picture placement; no note; no error;
  - put-first: the next edit is NOT refused (base is the newest version);
  - tab return: no save is sent from the old load; the first edit after the fresh read uses the newest base.

- [ ] **Step 2: Run** — `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-working-copy.test.ts src/features/site-editor/model/site-frame-sync.test.ts src/features/site-editor/hooks/use-site-editing-session.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement** `site-working-copy.ts` exactly as specified; rewire `use-site-document.ts` (a `visit` counter bumped by the adjust-state-on-prop-change pattern whenever `documentId` changes; the stored state carries the visit it was read in; return `LOADING` unless both match; keep the brand cache per document) and `use-site-editing-session.ts` as specified above. Keep every other behaviour of the session unchanged (images, annotations, versions, pages, URL bar, layers, inspector, the lock).

- [ ] **Step 4: Run** the three test files, the whole app suite (`npm test` in `apps/frontend`), lint on the touched files (`npx eslint <files>`).

- [ ] **Step 5: Commit** — `git commit -m "site editor: one working copy with a revision counter; only newer loads are adopted; canvas proposals over an older copy are refused"`

---

### Task 10: The standalone page reloads only for changes the session did not make (K3-3)

**Files:**
- Modify: `apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.ts` (add a pure helper)
- Modify: `apps/frontend/src/features/chat-shell/components/editor-surface.tsx:142-150`
- Test: `apps/frontend/src/features/design-editor/hooks/document-agent-run.logic.test.ts` (append; create if absent)

**Interfaces:**
- Produces: `siteReloadWanted({ polledVersion, knownVersion, runEnded }: { polledVersion: number | null; knownVersion: number | null; runEnded: boolean }): boolean` → `runEnded || (polledVersion !== null && (knownVersion === null || polledVersion > knownVersion))`.

- [ ] **Step 1: Failing test**

```ts
test("the standalone site reloads for someone else's write or a finished run, never for its own save", () => {
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: 6, runEnded: false }), false);
  assert.equal(siteReloadWanted({ polledVersion: 7, knownVersion: 6, runEnded: false }), true);
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: 6, runEnded: true }), true);
  assert.equal(siteReloadWanted({ polledVersion: 6, knownVersion: null, runEnded: false }), true);
});
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the helper; in `editor-surface.tsx`, keep the nonce effect but reload only when `siteReloadWanted({ polledVersion: agentRun.currentVersion, knownVersion: siteSession.saves.baseVersion, runEnded: <the run went from active to inactive since the last poll> })` (track the previous `active` in a ref updated inside the same effect).
- [ ] **Step 4: Run** the logic test and the chat-shell tests (`npx tsx --test src/features/chat-shell/**/*.test.ts` via the app's `npm test`).
- [ ] **Step 5: Commit** — `git commit -m "standalone artifact page: a site reloads for someone else's write or a finished run, not for its own saves"`

---

### Task 11: Scenario test: the canvas, the app and the server always agree

**Files:**
- Create: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.scenario.test.ts`

**What it does:** mounts the REAL `useSiteEditingSession` in jsdom over an in-memory repository (server copy + version + undo stack, CAS like `fixtureSiteRepository`), with an `<iframe>` bound to the session's `stage.canvas.iframeRef`, whose `contentWindow.postMessage` is replaced by a bridge into a REAL `FrameController` (no Puck: a fake `PuckHandle` that records shown pages). The controller's `post` dispatches `MessageEvent`s on `window` with `source = iframe.contentWindow` and `origin = editorOrigin`, and the nonce taken from `stage.canvas.src` (`#n=`). The session's editor-origin read is served by stubbing `fetch("/api/clue/site-editor/session")` with an `editorOrigin`.

**Sequence (each step followed by a settle):**
1. open the site (init lands; the frame shows rev R);
2. type on the canvas (`controller.pageEdited`, then flush) → one save;
3. a dock edit (`stage`'s inspector `onCommit`) while more canvas typing is pending in the frame → the patch keeps the typing; one save carries both;
4. an outside write on the server (simulating an agent checkpoint) + `session.reload()` → the frame shows it; pending typing dropped once;
5. ⌘Z from the frame (`controller.shortcut("undo")`) → the server steps back; the frame shows the stepped copy;
6. a save refused 422 → the frame shows the server copy (K1-4);
7. URL-bar reload during a slow save → nothing older is adopted.

**Assertion after every step:** `canonicalJson(frame.getState().site) === canonicalJson(session copy) === canonicalJson(server site)` once the queue is idle, and the server never received a save whose base was older than the version it last reported.

- [ ] Step 1: write the test (it fails before Tasks 8–9 land; write it after them and watch it pass; if any step fails, that is a bug to fix in Tasks 8–9, not a test to weaken).
- [ ] Step 2: run — `npx tsx --test src/features/site-editor/hooks/use-site-editing-session.scenario.test.ts`.
- [ ] Step 3: commit — `git commit -m "site editor: scenario test — canvas, app copy and server agree through typing, dock edits, agent writes, undo, refusals and reloads"`

---

### Task 12: Gates, review and the live walk

- [ ] Frontend gate: `cd apps/frontend && npm run design-system:build && npm run lint && npm run build` (0 errors).
- [ ] Suites: `npm test` (app), `npm test -w @clue/site-kit`, `npm test -w @clue/site-editor`, `npx tsc --noEmit -p packages/site-editor`.
- [ ] Browser harness (one file at a time, `CLUE_SITE_EDITOR_BROWSER=1`): `test_editor_renders.py`, `test_editor_containment.py`, `test_editor_history_keys.py`, `test_editor_selection_follows_section.py`.
- [ ] Re-run the reviewers' probes for every finding this plan closes and record each as fixed: S1 `resolve-cache`, `clone-canvas`; S2a `test_s2a_puck_history`, `test_s2a_selection_shift`; S2b `strict-mode-saves`, `step-queue-order`, `reload-during-save`, `tab-return-stale-load`; K3 `own_save_reload.mts`, `replace_during_init.mts`; K1 `refused-edit-stays-on-canvas.ts`; S3 `test_probe_s3_version_report.py`. Probes that asserted the old fault are expected to FAIL now; note each.
- [ ] One fresh reviewer (Opus) over this plan's diff only, findings verified first-hand, fixes test-first.
- [ ] Update `FINDINGS.md` statuses and the two verification docs' status lines for the closed findings; `_memory` entry.
- [ ] Live walk on trenton's stack (in-app browser): edit, dock edit, ⌘Z in a clone headline, move between two pages with different hero clones, reload during typing, two sites side by side.

---

## Phase 2 (after Task 12): instant undo

Approved direction (founder, 2026-10-14): optimistic undo plus prefetched undo snapshots; measure the validator's cost before changing the save path. A separate short plan is written after Phase 1 lands, because it depends on the working copy and revision counter from Task 9:
- the design API gains a read of the top few undo/redo snapshots (each undo envelope already stores the site as it stood before);
- on ⌘Z the app pushes the prefetched snapshot at once (`copy.edit`), runs the server undo, and on refusal reloads the server copy;
- timings of save/undo on trenton decide whether the validator gets a warm process.
