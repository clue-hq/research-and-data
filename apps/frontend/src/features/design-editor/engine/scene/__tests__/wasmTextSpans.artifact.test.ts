// @vitest-environment node
import { describe, expect, it } from "../../__tests__/vitest-shim";

import minimalSceneFixture from "./__fixtures__/minimal_scene.json";
import type { Scene, TextNode, TextSpan } from "../contracts";
import { updateTextNode } from "../operations";
import {
  formatStateForRange,
  spansVectorForContentEdit,
} from "../textSpans";
import { WasmEngine } from "../wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "./wasm-module-loader";

/**
 * Rung C, asked of the REAL vendored engine rather than of the port's own
 * beliefs (`docs/superpowers/plans/2026-08-24-rich-text-editing.md`).
 *
 * `textSpans.ts` is written against two engine behaviours it cannot test in
 * isolation, and the whole toolbar rides on both being true:
 *
 *  1. **D4 span honesty on the whole-kind replace path.** The platform twin of
 *     the design subsystem's own case
 *     (`subsystems/clue-design/apps/editor/src/engine/__tests__/wasmOperations.test.ts:520-554`):
 *     a content change carrying the OLD spans forward unchanged CLEARS them
 *     (stale byte offsets would silently mis-highlight the new string), the
 *     inverse frame restores content AND spans, and a re-authored, structurally
 *     different vector SURVIVES.
 *  2. **Spans round-trip.** What `updateTextNode(node, {content, spans})`
 *     writes is what `sceneJson()` gives back, byte for byte — which is what
 *     lets the toolbar read a committed range's state back off the document.
 *
 * The third case is the one this rung actually depends on: that
 * `spansVectorForContentEdit`'s deliberate no-op SPLIT is enough to defeat (1)
 * — i.e. that a session whose typing landed after every span keeps its styling
 * instead of watching the engine drop it.
 */

if (!wasmArtifactPresent) {
  console.log(
    "[wasmTextSpans.artifact] SKIPPED — no wasm artifact at public/vendor/wasm; " +
      "run `node scripts/copy-design-vendor.mjs` to vendor it.",
  );
}

const baseScene = minimalSceneFixture as unknown as Scene;

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** `node_contact_name` says "Dr. Priya Sharma" — 16 ASCII bytes. `Priya` is
 * bytes 4..9, which is the span upstream's own D4 case uses. */
const RED_PRIYA: TextSpan = {
  start: 4,
  end: 9,
  fill: { kind: "solid", color: { kind: "hex", value: "#ff0000" } },
};

function spannedScene(spans: TextSpan[] = [RED_PRIYA]): Scene {
  const scene = cloneScene(baseScene);
  (scene.nodes.node_contact_name.kind as TextNode).spans = spans;
  return scene;
}

function textKind(scene: Scene): TextNode {
  const kind = scene.nodes.node_contact_name.kind;
  expect(kind.kind).toBe("text");
  return kind as TextNode;
}

describe.skipIf(!wasmArtifactPresent)("scene text spans (real artifact)", () => {
  it("round-trips an authored spans vector through the engine and back out of sceneJson", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    const node = engine.scene.nodes.node_contact_name;

    const outcome = engine.applyOperations([
      updateTextNode(node, {
        content: "Dr. Priya Sharma",
        spans: [RED_PRIYA, { start: 10, end: 16, font_weight: 700, italic: true }],
      }),
    ]);

    expect(outcome.accepted).toBe(true);
    // The delta-maintained snapshot AND the engine's own serialization agree.
    const serialized = JSON.parse(engine.sceneJson()) as Scene;
    expect(textKind(serialized).spans).toEqual([
      RED_PRIYA,
      { start: 10, end: 16, font_weight: 700, italic: true },
    ]);
    expect(textKind(engine.scene).spans).toEqual(textKind(serialized).spans);

    // And what the toolbar reads back off the committed document is what the
    // user applied: `Priya` red, `Sharma` bold+italic, the space between them
    // carrying the node's own style.
    const stored = textKind(engine.scene);
    expect(formatStateForRange(stored, [4, 9])).toMatchObject({
      bold: "off",
      italic: "off",
      fill: { kind: "uniform", paint: RED_PRIYA.fill },
    });
    expect(formatStateForRange(stored, [10, 16])).toMatchObject({
      bold: "on",
      italic: "on",
    });
    expect(formatStateForRange(stored, [4, 16]).fill).toEqual({ kind: "mixed" });
  });

  it("D4: a content edit carrying byte-identical spans CLEARS them, and undo restores both", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, spannedScene());
    // Precondition: the engine round-trips the authored span.
    expect(textKind(engine.scene).spans).toEqual([RED_PRIYA]);

    const before = engine.scene.nodes.node_contact_name;
    const edit = engine.applyOperations([
      updateTextNode(before, { content: "Totally different headline" }),
    ]);

    expect(edit.accepted).toBe(true);
    expect(textKind(engine.scene).content).toBe("Totally different headline");
    expect(textKind(engine.scene).spans ?? []).toEqual([]);

    const undo = engine.applyOperations(edit.inverseOperations ?? []);
    expect(undo.accepted).toBe(true);
    expect(textKind(undo.scene).content).toBe("Dr. Priya Sharma");
    expect(textKind(undo.scene).spans).toEqual([RED_PRIYA]);
  });

  it("D4: a content edit carrying a RE-AUTHORED vector applies both channels", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, spannedScene());
    const before = engine.scene.nodes.node_contact_name;

    const edit = engine.applyOperations([
      updateTextNode(before, {
        content: "Totally different headline",
        spans: [{ start: 0, end: 7, font_weight: 700 }],
      }),
    ]);

    expect(edit.accepted).toBe(true);
    expect(textKind(engine.scene).content).toBe("Totally different headline");
    expect(textKind(engine.scene).spans).toEqual([
      { start: 0, end: 7, font_weight: 700 },
    ]);
  });

  it("the D4 EDGE: the split `spansVectorForContentEdit` authors defeats the clear", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, spannedScene());
    const before = engine.scene.nodes.node_contact_name;
    const stored = textKind(engine.scene).spans ?? [];

    // The session typed at the END of the string, so every span offset is
    // still correct and the maintained vector is byte-identical to the stored
    // one — precisely the shape the engine reads as a stale carry-forward.
    const draft = "Dr. Priya Sharma, MD";
    const vector = spansVectorForContentEdit(draft, stored, stored, true);
    // Semantically the same styling, structurally different: one span split in
    // two adjacent ones (adjacency is legal; only overlap is not).
    expect(vector).toEqual([
      { start: 4, end: 5, fill: RED_PRIYA.fill },
      { start: 5, end: 9, fill: RED_PRIYA.fill },
    ]);

    const edit = engine.applyOperations([
      updateTextNode(before, { content: draft, spans: vector }),
    ]);

    expect(edit.accepted).toBe(true);
    expect(textKind(engine.scene).content).toBe(draft);
    // SURVIVED. Without the split this vector would have been cleared, and the
    // user would have watched their styling vanish for typing a suffix.
    expect(textKind(engine.scene).spans).toEqual(vector);
    // `Priya` still reads as one uniformly red run, split or not.
    expect(formatStateForRange(textKind(engine.scene), [4, 9]).fill).toEqual({
      kind: "uniform",
      paint: RED_PRIYA.fill,
    });

    // And the whole thing is one undo frame back to the unsplit truth.
    const undo = engine.applyOperations(edit.inverseOperations ?? []);
    expect(undo.accepted).toBe(true);
    expect(textKind(undo.scene).content).toBe("Dr. Priya Sharma");
    expect(textKind(undo.scene).spans).toEqual([RED_PRIYA]);
  });
});
