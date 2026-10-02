# Agent-Working Chip (scene editor lock indicator) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Founder rules for SDD in this repo: implementers are **Opus** subagents only; review, verification, and rulings are the controller's. Commit locally, never push, no AI attribution.

**Goal:** While the design agent holds the scene editor lock, a persistent chip pinned to the top-left edge of the editor area shows a pulsing 3×3 dot grid and shimmering text reading "Designing. Please wait to edit.", so the user can see at a glance that the document is not theirs to edit yet.

**Architecture:** Purely presentational. The chip renders inside the existing `.sceneStage` container of `artifact-stage.tsx` and is shown iff the prop the stage already receives for the lock (`editDisabled`, fed by `agentRunLock.locked` in `chat-surface.tsx`) is true. No new state, no new data flow, no engine or transport change. Both animations are CSS keyframes in the chat-shell CSS module, with a `prefers-reduced-motion` fallback to static text. No new dependency.

**Tech Stack:** React 19 / Next 16 (App Router), CSS modules, node:test via `npx tsx --test`, `react-dom/server` for the render assertion.

**Spec:** Founder request 2026-09-03 with three reference screenshots (a "Designing. Please wait to edit." chip with a dotted-grid icon and a light sweep across the text, top-left of the canvas). The lock semantics are rung A of `docs/superpowers/plans/2026-09-02-scene-live-streaming.md` (no mid-run manual editing; `agent-run-lock.ts` decides `locked`).

## Rulings taken in this plan (founder may override)

- **R1 Copy.** The chip says `Designing. Please wait to edit.` (the screenshot's words). The Edit pill's tooltip keeps the ratified lock sentence from rung A unchanged; the chip is an additional surface, not a replacement.
- **R2 Position.** Top-left of the scene stage, 12 px inset, matching the screenshots (the founder allowed top-center as an alternative; left was shown three times).
- **R3 Scope.** Scene (ad) editor only. The website editor's lock is a deferred lane and gets nothing here.

## Global Constraints

- Frontend gate is `cd apps/frontend && npm run design-system:build && npm run lint && npm run build`; unit tests are node:test, run as `npx tsx --test <files>` from `apps/frontend`. Not vitest.
- Never invent UI beyond what is specified here: one chip, one position, one label. No new chrome elsewhere.
- Follow the CSS module's existing conventions: keyframes are declared in `chat-shell.module.css` beside `inspector-enter` / `toolbar-menu-enter`; colours come from the design-system tokens already used in that file (inspect the nearest pill/banner rule and reuse its variables; do not hard-code hex).
- The chip must not intercept pointer events on the canvas (`pointer-events: none`), must be announced once to assistive tech (`role="status"`, `aria-live="polite"`), and must not animate under `prefers-reduced-motion: reduce`.
- Commit rules: one commit, message below. No `Co-Authored-By`, no AI attribution. Never push. Never `git stash`. Work only in this worktree.

---

### Task 1: The chip, its styles, its wiring, its tests

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/agent-working-chip.tsx`
- Create: `apps/frontend/src/features/chat-shell/components/agent-working-chip.logic.ts`
- Create: `apps/frontend/src/features/chat-shell/components/agent-working-chip.test.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (`.sceneStage` rule ~line 1797; append the chip rules and keyframes)
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (~line 347, inside the `.sceneStage` div, before `<SceneArtifactCanvas`)

**Interfaces:**
- Consumes: `editDisabled?: boolean` already on `ArtifactStage`'s props (line ~128) and already passed from `chat-surface.tsx` as `agentRunLock.locked`.
- Produces:
  - `AGENT_WORKING_CHIP_LABEL = "Designing. Please wait to edit."`
  - `shouldShowAgentWorkingChip({ editDisabled, hasScene }: { editDisabled: boolean | undefined; hasScene: boolean }): boolean` — true only when the lock is engaged AND a scene is actually on the stage (the chip never floats over the empty-state card).
  - `AgentWorkingChip({ label }: { label: string }): JSX.Element`

- [x] **Step 1: Write the failing tests**

Create `apps/frontend/src/features/chat-shell/components/agent-working-chip.test.tsx`:

```tsx
import assert from "node:assert/strict";
import { it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AgentWorkingChip } from "./agent-working-chip";
import { AGENT_WORKING_CHIP_LABEL, shouldShowAgentWorkingChip } from "./agent-working-chip.logic";

it("shows only while the lock is engaged over a real scene", () => {
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: true, hasScene: true }), true);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: false, hasScene: true }), false);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: undefined, hasScene: true }), false);
  assert.equal(shouldShowAgentWorkingChip({ editDisabled: true, hasScene: false }), false);
});

it("carries the founder's words, verbatim", () => {
  assert.equal(AGENT_WORKING_CHIP_LABEL, "Designing. Please wait to edit.");
});

it("renders a polite status with a nine-dot grid and the label", () => {
  const html = renderToStaticMarkup(<AgentWorkingChip label={AGENT_WORKING_CHIP_LABEL} />);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/data-dot=""/g) ?? []).length, 9);
  assert.match(html, /Designing\. Please wait to edit\./);
  // The grid is decorative; the label is the accessible name.
  assert.match(html, /aria-hidden="true"/);
});
```

- [x] **Step 2: Run the tests to verify they fail**

Run from `apps/frontend`: `npx tsx --test src/features/chat-shell/components/agent-working-chip.test.tsx`
Expected: failure to resolve `./agent-working-chip` / `./agent-working-chip.logic`.

- [x] **Step 3: Write the logic module**

Create `apps/frontend/src/features/chat-shell/components/agent-working-chip.logic.ts`:

```ts
/**
 * The agent-working chip's two facts (founder request 2026-09-03).
 *
 * Kept apart from the component so the visibility rule is testable without a DOM:
 * the chip is the VISIBLE form of the scene editor's agent-run lock (rung A of the
 * live-streaming plan), so it shows exactly when that lock is engaged — and only
 * over a real scene, never over the empty-state card.
 */

/** The founder's words, verbatim (ruling R1 in the plan). The Edit pill's tooltip
 * keeps rung A's ratified lock sentence; this is the chip's own line. */
export const AGENT_WORKING_CHIP_LABEL = "Designing. Please wait to edit.";

export function shouldShowAgentWorkingChip({
  editDisabled,
  hasScene,
}: {
  /** `ArtifactStage`'s `editDisabled` — `agentRunLock.locked` upstream. */
  editDisabled: boolean | undefined;
  /** Whether a scene is on the stage (the same condition that mounts the canvas). */
  hasScene: boolean;
}): boolean {
  return editDisabled === true && hasScene;
}
```

- [x] **Step 4: Write the component**

Create `apps/frontend/src/features/chat-shell/components/agent-working-chip.tsx`:

```tsx
import styles from "./chat-shell.module.css";

/**
 * "Designing. Please wait to edit." — the persistent chip pinned to the top-left edge
 * of the scene stage while the design agent holds the editor lock.
 *
 * Purely presentational: the caller decides visibility (`shouldShowAgentWorkingChip`).
 * The nine-dot grid pulses and the label shimmers, both in CSS (see the
 * `agentWorking*` rules in the module); under `prefers-reduced-motion` both are
 * static. `pointer-events: none` in the CSS keeps it out of the canvas's way.
 */
export function AgentWorkingChip({ label }: { label: string }) {
  return (
    <div aria-live="polite" className={styles.agentWorkingChip} role="status">
      <span aria-hidden="true" className={styles.agentWorkingGrid}>
        {Array.from({ length: 9 }, (_, index) => (
          <span className={styles.agentWorkingDot} data-dot="" key={index} />
        ))}
      </span>
      <span className={styles.agentWorkingLabel}>{label}</span>
    </div>
  );
}
```

- [x] **Step 5: Add the styles**

In `chat-shell.module.css`, change `.sceneStage` so the chip can pin to it:

```css
.sceneStage {
  position: relative; /* the agent-working chip pins to this edge */
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}
```

Then append, beside the existing keyframes (after `toolbar-menu-enter` is fine), using the SAME token variables the file's nearest pill or banner rule uses for surface, border, shadow, and accent text (read those rules first and substitute their variable names for the placeholders `<surface>`, `<border>`, `<shadow>`, `<accent>`, `<accent-muted>` below — do not leave placeholders and do not hard-code hex):

```css
/*
 * Agent-working chip (founder request 2026-09-03): the visible form of the scene
 * editor's agent-run lock. Pinned top-left of `.sceneStage`, never intercepts the
 * pointer, animates a 3×3 dot pulse and a text shimmer; static under reduced motion.
 */
.agentWorkingChip {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 4;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 10px;
  border-radius: 999px;
  background: <surface>;
  border: 1px solid <border>;
  box-shadow: <shadow>;
  pointer-events: none;
  user-select: none;
  font-size: 13px;
  line-height: 1;
  white-space: nowrap;
}

.agentWorkingGrid {
  display: grid;
  grid-template-columns: repeat(3, 3px);
  grid-auto-rows: 3px;
  gap: 2px;
}

.agentWorkingDot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: <accent>;
  opacity: 0.25;
  animation: agent-working-dot 1.2s ease-in-out infinite;
}
.agentWorkingDot:nth-child(1) { animation-delay: 0s; }
.agentWorkingDot:nth-child(2) { animation-delay: 0.1s; }
.agentWorkingDot:nth-child(3) { animation-delay: 0.2s; }
.agentWorkingDot:nth-child(4) { animation-delay: 0.1s; }
.agentWorkingDot:nth-child(5) { animation-delay: 0.2s; }
.agentWorkingDot:nth-child(6) { animation-delay: 0.3s; }
.agentWorkingDot:nth-child(7) { animation-delay: 0.2s; }
.agentWorkingDot:nth-child(8) { animation-delay: 0.3s; }
.agentWorkingDot:nth-child(9) { animation-delay: 0.4s; }

.agentWorkingLabel {
  color: transparent;
  background-image: linear-gradient(
    90deg,
    <accent> 0%,
    <accent> 35%,
    <accent-muted> 50%,
    <accent> 65%,
    <accent> 100%
  );
  background-size: 250% 100%;
  background-position: 100% 0;
  -webkit-background-clip: text;
  background-clip: text;
  animation: agent-working-shimmer 2.2s linear infinite;
}

@keyframes agent-working-dot {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}

@keyframes agent-working-shimmer {
  from { background-position: 100% 0; }
  to { background-position: 0% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .agentWorkingDot { animation: none; opacity: 0.7; }
  .agentWorkingLabel { animation: none; background: none; color: <accent>; }
}
```

- [x] **Step 6: Wire it into the stage**

In `artifact-stage.tsx`, import both:

```tsx
import { AgentWorkingChip } from "./agent-working-chip";
import { AGENT_WORKING_CHIP_LABEL, shouldShowAgentWorkingChip } from "./agent-working-chip.logic";
```

and inside the `<div aria-label="Ad output canvas" className={styles.sceneStage}>` element, as its FIRST child (before `<SceneArtifactCanvas`), add:

```tsx
                {shouldShowAgentWorkingChip({ editDisabled, hasScene: true }) ? (
                  <AgentWorkingChip label={AGENT_WORKING_CHIP_LABEL} />
                ) : null}
```

(`hasScene: true` is correct at that site: the `.sceneStage` branch only renders when a scene is on the stage; the empty-state card is the other branch. If the branch condition is a named variable in scope, pass that variable instead of `true` and say so in the report.)

- [x] **Step 7: Run the tests and the gate**

From `apps/frontend`:

```
npx tsx --test src/features/chat-shell/components/agent-working-chip.test.tsx
npm run design-system:build && npm run lint && npm run build
```

Expected: 3 tests pass; lint reports the two pre-existing `canvasOperations.ts` warnings only; build compiles. Then run the chat-shell suite: `find src/features/chat-shell -name "*.test.ts*" -print0 | xargs -0 npx tsx --test` — all pass.

- [x] **Step 8: Commit**

```
git add apps/frontend/src/features/chat-shell/components/agent-working-chip.tsx apps/frontend/src/features/chat-shell/components/agent-working-chip.logic.ts apps/frontend/src/features/chat-shell/components/agent-working-chip.test.tsx apps/frontend/src/features/chat-shell/components/chat-shell.module.css apps/frontend/src/features/chat-shell/components/artifact-stage.tsx
git commit -m "feat(chat-shell): agent-working chip — the visible form of the scene editor lock

While the design agent holds the lock, a chip pinned top-left of the scene stage shows a
pulsing 3x3 dot grid and shimmering 'Designing. Please wait to edit.' (founder request
2026-09-03). Driven by the lock the stage already receives; CSS-only animation with a
reduced-motion fallback; never intercepts the pointer."
```

Live check (controller, after the commit): open the Apollo document during a running design turn and confirm the chip appears at the top-left edge, animates, and disappears when the turn releases the lock.
