import { canvasDragOperation, canvasResizeOperation } from "@/engine/canvasOperations";
import type { Operation, Scene } from "@/engine/contracts";
import { updateNodeTransform, updateTextNode } from "@/engine/operations";
import { clampNodeTransformToParentBounds } from "@/engine/sceneQueries";
import {
  modifyNodeStacksEdit,
  modifyPageNameEdit,
  type StructuredEdit
} from "@/engine/structuredEdits";

/**
 * Track E W6 conformance: one deterministic gesture script covering the
 * editor's edit surfaces — canvas drag, canvas resize, inspector text
 * edit, keyboard nudge, effects stack edit, page rename. The same script
 * runs through the legacy TS path and the WASM engine; the captured
 * envelopes (wire payloads + canonical operations) and the final scene
 * must be IDENTICAL, byte for byte, between the two.
 *
 * The legacy path's output is pinned in
 * `fixtures/wasm-conformance/gesture-envelopes.json`, captured before W4
 * retired the mirrors.
 */

export interface GestureEnvelope {
  step: string;
  kind: "operations" | "structured_edit";
  /** The wire payload the editor persists (operation batch or edit JSON). */
  payload: unknown;
  /** Canonical operations applied locally for the step. */
  operations: Operation[];
}

export interface GestureScriptResult {
  envelopes: GestureEnvelope[];
  finalScene: Scene;
}

export interface GesturePort {
  readonly scene: Scene;
  applyOperations(operations: Operation[]): {
    accepted: boolean;
    scene: Scene;
    message?: string;
  };
  /** WASM engines lower structured edits natively. */
  applyStructuredEdit?(edit: StructuredEdit): {
    accepted: boolean;
    scene: Scene;
    operations: Operation[];
    message?: string;
  };
}

export interface GestureScriptOptions {
  /**
   * Legacy fallback: lower a structured edit to optimistic operations in
   * TS (the mirror retired at W4). Required when the port has no native
   * applyStructuredEdit.
   */
  structuredEditFallback?: (scene: Scene, edit: StructuredEdit) => Operation[];
}

export function runGestureScript(
  port: GesturePort,
  options: GestureScriptOptions = {}
): GestureScriptResult {
  const envelopes: GestureEnvelope[] = [];

  const applyOperationStep = (step: string, operation: Operation | null) => {
    if (!operation) {
      throw new Error(`gesture step ${step} produced no operation`);
    }
    const outcome = port.applyOperations([operation]);
    if (!outcome.accepted) {
      throw new Error(`gesture step ${step} rejected: ${outcome.message ?? "unknown"}`);
    }
    envelopes.push({
      step,
      kind: "operations",
      payload: [operation],
      operations: [operation]
    });
  };

  const applyStructuredEditStep = (step: string, edit: StructuredEdit) => {
    if (port.applyStructuredEdit) {
      const outcome = port.applyStructuredEdit(edit);
      if (!outcome.accepted) {
        throw new Error(`gesture step ${step} rejected: ${outcome.message ?? "unknown"}`);
      }
      envelopes.push({
        step,
        kind: "structured_edit",
        payload: edit,
        operations: outcome.operations
      });
      return;
    }
    const fallback = options.structuredEditFallback;
    if (!fallback) {
      throw new Error(`gesture step ${step}: no structured edit path available`);
    }
    const operations = fallback(port.scene, edit);
    if (operations.length === 0) {
      throw new Error(`gesture step ${step}: fallback produced no operations`);
    }
    const outcome = port.applyOperations(operations);
    if (!outcome.accepted) {
      throw new Error(`gesture step ${step} rejected: ${outcome.message ?? "unknown"}`);
    }
    envelopes.push({
      step,
      kind: "structured_edit",
      payload: edit,
      operations
    });
  };

  const node = () => {
    const current = port.scene.nodes.node_contact_name;
    if (!current) {
      throw new Error("gesture script requires node_contact_name");
    }
    return current;
  };
  const page = () => {
    const current = port.scene.pages.page_a4;
    if (!current) {
      throw new Error("gesture script requires page_a4");
    }
    return current;
  };

  // 1. Canvas drag (pointer gesture commit).
  applyOperationStep(
    "drag_node",
    canvasDragOperation({
      scene: port.scene,
      node: node(),
      page: page(),
      pageOrigin: { x: 0, y: 0 },
      canvasX: 60,
      canvasY: 88
    })
  );

  // 2. Canvas resize (transformer gesture commit).
  applyOperationStep(
    "resize_node",
    canvasResizeOperation({
      scene: port.scene,
      node: node(),
      page: page(),
      pageOrigin: { x: 0, y: 0 },
      transform: {
        canvasX: 58,
        canvasY: 84,
        rotation: 0,
        scaleX: 1.2,
        scaleY: 1.1
      }
    })
  );

  // 3. Inspector text edit (per-keystroke commit shape).
  applyOperationStep(
    "text_edit",
    updateTextNode(node(), { content: "Conformance headline", font_size: 21 })
  );

  // 4. Keyboard nudge (ArrowRight).
  applyOperationStep(
    "keyboard_nudge",
    updateNodeTransform(
      node(),
      clampNodeTransformToParentBounds(port.scene, node(), {
        ...node().transform,
        x: node().transform.x + 1
      })
    )
  );

  // 5. Effects surface: add a drop shadow stack entry (structured edit).
  applyStructuredEditStep(
    "effects_add_shadow",
    modifyNodeStacksEdit(node().id, {
      effectEdits: [
        {
          kind: "add",
          entry: {
            id: "shadow_soft",
            kind: {
              kind: "drop_shadow",
              color: { kind: "hex", value: "#000000" },
              opacity: 0.18,
              x: 0.0,
              y: 8.0,
              blur: 24.0,
              spread: 0.0
            }
          }
        }
      ]
    })
  );

  // 6. Page rename (structured edit).
  applyStructuredEditStep("page_rename", modifyPageNameEdit("page_a4", "Conformance page"));

  return {
    envelopes,
    finalScene: port.scene
  };
}
