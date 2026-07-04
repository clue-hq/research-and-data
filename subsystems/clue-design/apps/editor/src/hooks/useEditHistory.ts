import { useState, type Dispatch, type SetStateAction } from "react";
import type {
  BrandCompatibilityReport,
  Diagnostic,
  Operation,
  Scene
} from "@/engine/contracts";
import type { EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";

/** One undo/redo step: the scene BEFORE the batch applied, the batch, the
 * engine-computed inverse of the batch (null when the engine could not
 * invert it), and whether the batch reached the server — an undo of a
 * persisted, non-invertible batch is the one case that must warn. */
export interface EditorHistoryFrame {
  scene: Scene;
  operations: Operation[];
  inverseOperations: Operation[] | null;
  persisted: boolean;
}

/**
 * The editor's local undo/redo history: bounded frame stacks (50), the
 * rolling operation log, and the last-applied operation.
 *
 * This hook owns pure history MECHANICS only — it knows nothing about the
 * agent turn lock. The canvas-lock guards (pending review / turn running)
 * live at the EditorApp orchestration layer alongside the other guarded
 * mutation paths, so `undo`/`redo` here must only be called through them.
 *
 * The deps object is rebuilt every render (same closure semantics as the
 * inline originals) — never memoize it.
 */
export interface UseEditHistoryDeps {
  scene: Scene;
  replaceScene: (nextScene: Scene) => void;
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
  setBrandCompatibilityReport: Dispatch<SetStateAction<BrandCompatibilityReport | null>>;
  setPreflightResult: Dispatch<SetStateAction<EditorPreflightResult | null>>;
  setExportResult: Dispatch<SetStateAction<EditorExportResult | null>>;
  setWorkspaceMode: Dispatch<SetStateAction<"canvas" | "export" | "compare">>;
  /** Persist a history step through the ordinary document-operations path
   * (an undo posts the frame's inverse batch; a redo re-posts the original
   * batch), so the server document tracks local history instead of drifting
   * until the next reconcile. Passed as a lazy wrapper — document sync is
   * wired after this hook — and only called from event handlers. */
  persistHistoryStep: (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene
  ) => unknown;
}

export function useEditHistory(deps: UseEditHistoryDeps) {
  const {
    scene,
    replaceScene,
    setDiagnostics,
    setBrandCompatibilityReport,
    setPreflightResult,
    setExportResult,
    setWorkspaceMode,
    persistHistoryStep
  } = deps;

  const [lastOperation, setLastOperation] = useState<Operation | null>(null);
  const [undoStack, setUndoStack] = useState<EditorHistoryFrame[]>([]);
  const [redoStack, setRedoStack] = useState<EditorHistoryFrame[]>([]);
  const [operationHistory, setOperationHistory] = useState<Operation[]>([]);

  const undo = () => {
    const undoFrame = undoStack[undoStack.length - 1];
    if (!undoFrame) {
      return;
    }

    const nextHistory =
      undoFrame.operations.length > 0
        ? operationHistory.slice(0, -undoFrame.operations.length)
        : operationHistory;

    setUndoStack((stack) => stack.slice(0, -1));
    setRedoStack((stack) => [
      ...stack.slice(-49),
      {
        scene,
        operations: undoFrame.operations,
        inverseOperations: undoFrame.inverseOperations,
        persisted: undoFrame.persisted
      }
    ]);
    setOperationHistory(nextHistory);
    replaceScene(undoFrame.scene);
    setLastOperation(nextHistory[nextHistory.length - 1] ?? null);
    setDiagnostics([]);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    // Persist the undo as an ordinary forward batch of the frame's inverse
    // ops — the server history stays append-only and in step with the canvas.
    if (undoFrame.inverseOperations && undoFrame.inverseOperations.length > 0) {
      persistHistoryStep(scene, undoFrame.inverseOperations, undoFrame.scene);
    } else if (undoFrame.persisted) {
      setDiagnostics([
        {
          severity: "warning",
          phase: "operation",
          code: "EDITOR_UNDO_NOT_PERSISTED",
          message:
            "This undo could not be persisted (the batch was not invertible); the server document still has the undone change.",
          subject: { kind: "document" },
          hint: "The next saved edit reconciles the document. Redo restores the change everywhere."
        }
      ]);
    }
  };

  const redo = () => {
    const redoFrame = redoStack[redoStack.length - 1];
    if (!redoFrame) {
      return;
    }

    setRedoStack((stack) => stack.slice(0, -1));
    setUndoStack((stack) => [
      ...stack.slice(-49),
      {
        scene,
        operations: redoFrame.operations,
        inverseOperations: redoFrame.inverseOperations,
        persisted: redoFrame.persisted
      }
    ]);
    setOperationHistory((history) => [...history, ...redoFrame.operations].slice(-50));
    replaceScene(redoFrame.scene);
    setLastOperation(redoFrame.operations[redoFrame.operations.length - 1] ?? null);
    setDiagnostics([]);
    setBrandCompatibilityReport(null);
    setPreflightResult(null);
    setExportResult(null);
    setWorkspaceMode("canvas");
    // A redo re-persists the original batch (append-only, like undo above).
    persistHistoryStep(scene, redoFrame.operations, redoFrame.scene);
  };

  return {
    lastOperation,
    setLastOperation,
    undoStack,
    setUndoStack,
    redoStack,
    setRedoStack,
    operationHistory,
    setOperationHistory,
    undo,
    redo
  };
}
