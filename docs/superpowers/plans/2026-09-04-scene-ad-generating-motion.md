# Scene-Ad Generating Motion (port of the co-founder's handoff) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scene-ad editor's top-left "Designing. Please wait to edit." chip with the co-founder's approved ad motion: the input lock + chip (Clue-mark spinner, shimmering text) and the edge glow, ported verbatim from branch `handoff/output-pane-generating-motion`. Nothing from the website veil is ported.

**Architecture:** Three files come across from the handoff's `components/` folder (`generating.css` trimmed to the glow, the lock and the shared keyframes; `clue-mark.tsx`; `generating-glow.tsx`; `ad-designing-lock.tsx`) into `apps/frontend/src/features/design-editor/components/generating/`. `ArtifactStage` mounts the lock and the glow as siblings of the scene canvas inside `.sceneStage`, driven by one boolean `agentWorking` that `chat-surface.tsx` feeds from the existing `sceneLocked` (the agent-run lock), gated on a real scene exactly as the old chip was. The old chip component, its logic, its test and its CSS block are deleted.

**Tech Stack:** Next 16 App Router (a plain global stylesheet imported from the component file), React, `cn` from `@/lib/utils`; tests with `node:test` + `react-dom/server` (`npx tsx --test`); no new dependency.

**Spec:** `HANDOVER.md` and `README.md` on `origin/handoff/output-pane-generating-motion` (fetched; also extracted at `/tmp/gen-preview/`). The ad preview `/tmp/gen-preview/preview/ad.html` is the visual target (screenshot `/tmp/plan4-evidence-keep/gen-ad-preview.png`).

## Global Constraints

- One Opus implementer; the controller reviews the diff and re-runs every test first-hand. Commit locally, never push, no AI attribution, never `git stash`. Stage by explicit path (the tree carries untracked golden PNGs on purpose).
- Port ONLY the scene-ad pieces: `AdDesigningLock`, `GeneratingGlow`, `ClueMark`, and the CSS they need (glow section, lock section, the `clue-gen-shimmer` keyframes, the `:root` variables, the host helper, the reduced-motion block). Do NOT port `website-generating-veil.tsx` or the veil CSS (section 2: `.clue-gen-veil*`, `.clue-gen-mark`, `.clue-gen-title`, `.clue-gen-hint`, `clue-gen-drift`, `clue-gen-p1/2/3`). The reduced-motion block keeps only the selectors that still exist.
- Component source is copied verbatim except: the header comment of `generating.css` (describe two pieces, not three; note the stacking change), the z-index change below, and the barrel (no veil export). Copy is the handoff's approved default: "Agent is designing. Please wait." — it supersedes the 2026-09-03 chip wording, and the memo records that.
- Stacking (controller ruling): inside `.sceneStage` the scene canvas already paints its banners at z-index 40 and the caret textarea at 41 (`scene-artifact-canvas.module.css`). The handoff's glow (7) and lock (8) would sit under them. In the ported CSS set `.clue-gen-glow { z-index: 42 }` and `.clue-gen-lock { z-index: 43 }` with a one-line comment naming those two overlays. `.sceneStage` gains `isolation: isolate` (through the `clue-gen-host` class) so the effect's stacking is local to the stage.
- Behaviour accepted from the handoff: while active the lock shields pointer input on the canvas surface (a click selects nothing; wheel zoom/pan is swallowed too), and `cursor: progress`. The existing `gestureDisabled` / inspector plumbing stays untouched.
- `npm run design-system:build && npm run lint && npm run build` is the handoff's gate; `npm test` too. The React Compiler lint refuses ref reads in JSX and derived values between hooks.

---

### Task 1: Port the lock and the glow; retire the chip

**Files:**
- Create: `apps/frontend/src/features/design-editor/components/generating/generating.css`
- Create: `apps/frontend/src/features/design-editor/components/generating/clue-mark.tsx` (verbatim from the handoff)
- Create: `apps/frontend/src/features/design-editor/components/generating/generating-glow.tsx` (verbatim)
- Create: `apps/frontend/src/features/design-editor/components/generating/ad-designing-lock.tsx` (verbatim)
- Create: `apps/frontend/src/features/design-editor/components/generating/index.ts` (barrel without the veil)
- Create: `apps/frontend/src/features/design-editor/components/generating/scene-agent-motion.ts` (the visibility rule)
- Create: `apps/frontend/src/features/design-editor/components/generating/generating.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx` (imports ~line 43–46; the scene stage block ~line 348–360; props ~line 67 / 133)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (the `<ArtifactStage` mount ~line 752–835: add `agentWorking={sceneLocked}`)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-shell.module.css` (delete the agent-working chip block ~line 3285–3413, i.e. from the `/* Agent-working chip … */` comment through the reduced-motion rules for `.agentWorkingDot`/`.agentWorkingLabel`; update the `.sceneStage` comment ~line 1798)
- Delete: `apps/frontend/src/features/chat-shell/components/agent-working-chip.tsx`, `agent-working-chip.logic.ts`, `agent-working-chip.test.ts`

**Interfaces:**
- Consumes: `cn` from `@/lib/utils`; `sceneLocked` in `chat-surface.tsx` (already computed: `agentRunLock.locked && shell.artifactKind === "ad"`).
- Produces: `ArtifactStage` prop `agentWorking?: boolean` (default `false`; `editor-surface.tsx`'s standalone mount passes nothing); `sceneAgentMotionActive({ agentWorking, hasScene }): boolean`; components `AdDesigningLock`, `GeneratingGlow`, `ClueMark`.

- [ ] **Step 1: Bring the files across and write the failing tests**

Source files: `git show origin/handoff/output-pane-generating-motion:components/<name>` (or `/tmp/gen-preview/components/<name>`). Copy `clue-mark.tsx`, `generating-glow.tsx`, `ad-designing-lock.tsx` byte-for-byte. Write `generating.css` as the handoff file minus section 2 (see Global Constraints), with the header comment rewritten to describe the two pieces and the stacking numbers, and the two z-index lines changed:

```css
.clue-gen-glow {
  position: absolute; inset: 0; z-index: 42; /* above the canvas's banners (40) and caret textarea (41) */
  ...
.clue-gen-lock {
  position: absolute; inset: 0; z-index: 43; /* the chip over the glow, both over every canvas overlay */
```

`index.ts`:

```ts
export { ClueMark, CLUE_MARK_PATHS, CLUE_MARK_VIEWBOX } from "./clue-mark";
export { GeneratingGlow, type GeneratingGlowProps } from "./generating-glow";
export { AdDesigningLock, type AdDesigningLockProps } from "./ad-designing-lock";
export { sceneAgentMotionActive } from "./scene-agent-motion";
```

`scene-agent-motion.ts`:

```ts
/**
 * When the scene-ad editor shows the agent-working motion (the co-founder's
 * lock + glow, ported 2026-09-04 from `handoff/output-pane-generating-motion`).
 *
 * The rule the retired chip had, kept apart from the components so it is
 * testable without a DOM: the motion is the VISIBLE form of the scene editor's
 * agent-run lock, so it runs exactly while that lock is engaged — and only
 * over a real scene, never over the empty-state card.
 */
export function sceneAgentMotionActive({
  agentWorking,
  hasScene,
}: {
  /** `chat-surface.tsx`'s `sceneLocked`: the agent-run lock over an ad artifact. */
  agentWorking: boolean | undefined;
  /** Whether a scene is on the stage (the same condition that mounts the canvas). */
  hasScene: boolean;
}): boolean {
  return agentWorking === true && hasScene;
}
```

`generating.test.ts`:

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AdDesigningLock } from "./ad-designing-lock";
import { GeneratingGlow } from "./generating-glow";
import { sceneAgentMotionActive } from "./scene-agent-motion";

it("runs only while the lock is engaged over a real scene", () => {
  assert.equal(sceneAgentMotionActive({ agentWorking: true, hasScene: true }), true);
  assert.equal(sceneAgentMotionActive({ agentWorking: false, hasScene: true }), false);
  assert.equal(sceneAgentMotionActive({ agentWorking: undefined, hasScene: true }), false);
  assert.equal(sceneAgentMotionActive({ agentWorking: true, hasScene: false }), false);
});

it("the lock is a polite status carrying the Clue mark spinner and the approved copy", () => {
  const html = renderToStaticMarkup(createElement(AdDesigningLock, { active: true }));
  assert.match(html, /class="clue-gen-lock"/);
  assert.match(html, /data-active="true"/);
  assert.match(html, /data-placement="top-left"/);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.equal((html.match(/<path /g) ?? []).length, 3, "three mark pieces, in order");
  assert.match(html, /class="clue-gen-spinner"/);
  assert.match(html, /Agent is designing\. Please wait\./);
});

it("an inactive lock stays mounted, hidden from assistive tech, and takes no input", () => {
  const html = renderToStaticMarkup(createElement(AdDesigningLock, { active: false }));
  assert.match(html, /data-active="false"/);
  assert.match(html, /aria-hidden="true"/);
});

it("the glow is four decorative layers and never a landmark", () => {
  const html = renderToStaticMarkup(createElement(GeneratingGlow, { active: true }));
  assert.match(html, /class="clue-gen-glow"/);
  assert.match(html, /aria-hidden="true"/);
  for (const layer of ["haze", "bloom", "line", "rim"]) {
    assert.match(html, new RegExp(`clue-gen-glow__${layer}`));
  }
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/components/generating/generating.test.ts 2>&1 | tail -6`
Expected: fails until the four source files exist (module not found), then passes once they do — the component files are verbatim, so this test is the port's shape check, not a red-to-green implementation.

- [ ] **Step 3: Mount it, thread the signal, retire the chip**

`artifact-stage.tsx`:
- Replace the chip imports with `import "@/features/design-editor/components/generating/generating.css";` and `import { AdDesigningLock, GeneratingGlow, sceneAgentMotionActive } from "@/features/design-editor/components/generating";`.
- Add the prop (next to `editDisabled`): `/** Scene-ad motion (2026-09-04 port): true while the agent-run lock holds over this ad — `chat-surface.tsx`'s `sceneLocked`. The standalone artifact route has no turn stream and leaves it unset. */ agentWorking?: boolean;` destructured with default `false`.
- In the scene stage block, compute `const sceneMotion = sceneAgentMotionActive({ agentWorking, hasScene: Boolean(activeDocumentId) });` BELOW every hook (the React Compiler rule), and render:

```tsx
              <div aria-label="Ad output canvas" className={`${styles.sceneStage} clue-gen-host`}>
                <SceneArtifactCanvas ... unchanged ... />
                {/* The co-founder's agent-working motion (handoff 2026-09-04):
                    the artwork stays visible and keeps updating live; a
                    transparent shield swallows canvas input and a chip with the
                    Clue-mark spinner says the agent is mid-edit; a thin light
                    frame drifts round the stage's edges. Both fade on their own
                    when `active` drops — they stay mounted so the exit
                    transition can play. Stacking is theirs (42/43), above the
                    canvas's banners and caret. */}
                <AdDesigningLock active={sceneMotion} />
                <GeneratingGlow active={sceneMotion} />
              </div>
```

`chat-surface.tsx`: add `agentWorking={sceneLocked}` beside `editDisabled={...}` with a two-line comment: the motion follows the CANVAS lock (`sceneLocked`), not the Edit pill's `editDisabled`, so it also runs when the lock engages mid-edit (leaving edit mode is never refused, so `editDisabled` is false there).

`chat-shell.module.css`: delete the whole agent-working chip block (comment, `.agentWorkingChip`, `.agentWorkingGrid`, `.agentWorkingDot` + its nine `:nth-child` rules and keyframes, `.agentWorkingLabel` + keyframes, and the reduced-motion rules for them). Change the `.sceneStage` comment to `/* the agent-working motion (lock + glow) pins to this box */`.

Delete the three `agent-working-chip*` files. `grep -rn "agentWorking\|AgentWorking\|AGENT_WORKING" apps/frontend/src` must then return only the new `agentWorking` prop and `sceneAgentMotionActive`.

- [ ] **Step 4: Gates**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/components/generating/generating.test.ts 2>&1 | tail -4 && npm run lint 2>&1 | tail -4 && npm test 2>&1 | tail -5 && npm run design-system:build 2>&1 | tail -2 && npm run build 2>&1 | tail -8`
Expected: 4 tests pass; lint 0 errors (2 pre-existing warnings in `canvasOperations.ts`); `npm test` all pass (one pre-existing jsdom skip; the deleted chip test is gone); design-system build and `next build` succeed. A failing build over the global CSS import is a stop: report NEEDS_CONTEXT with the error.

- [ ] **Step 5: Commit** (explicit paths)

```bash
git add apps/frontend/src/features/design-editor/components/generating apps/frontend/src/features/chat-shell/components/artifact-stage.tsx apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/chat-shell/components/chat-shell.module.css
git rm -q apps/frontend/src/features/chat-shell/components/agent-working-chip.tsx apps/frontend/src/features/chat-shell/components/agent-working-chip.logic.ts apps/frontend/src/features/chat-shell/components/agent-working-chip.test.ts
git commit -m "feat(design-editor): scene-ad agent-working motion — lock, chip and edge glow from the co-founder's handoff

Ports AdDesigningLock, GeneratingGlow and ClueMark (verbatim) with the glow and
lock sections of generating.css from handoff/output-pane-generating-motion,
mounted inside .sceneStage and driven by the canvas lock (sceneLocked). The
top-left 'Designing. Please wait to edit.' chip, its logic, test and CSS are
retired. The website veil is not ported. Stacking raised above the canvas's
banners (40) and caret (41)."
```

---

### Task 2: Live proof (controller)

- [ ] Open the Apollo ad in the editor (Edit mode), send a small change request in its thread, and while the turn runs capture: the chip top-left with the spinning mark and shimmering text, the edge glow round the stage, the artwork still updating, a click on a node selecting nothing, the inspector inert; on the terminal turn frame both fade and editing resumes. Screenshots to `/tmp/plan4-evidence-keep/motion-*.png`.
- [ ] Reduced motion: emulate `prefers-reduced-motion: reduce` if the browser tool allows; otherwise inspect the stylesheet's block.
- [ ] Memo `_memory/2026-09-04-scene-ad-generating-motion.md`; note that the founder's 2026-09-03 chip wording is superseded by the handoff copy.
