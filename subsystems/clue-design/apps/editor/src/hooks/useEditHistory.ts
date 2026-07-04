import { useState, type Dispatch, type SetStateAction } from "react";
import type {
  BrandCompatibilityReport,
  Diagnostic,
  Operation,
  Scene
} from "@/engine/contracts";
import type { EditorExportResult } from "@/engine/exportRunner";
import type { EditorPreflightResult } from "@/engine/preflightRunner";

/** One undo/redo step: the scene BEFORE the batch applied, plus the batch. */
export interface EditorHistoryFrame {
  scene: Scene;
  operations: Operation[];
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
}

export function useEditHistory(deps: UseEditHistoryDeps) {
  const {
    scene,
    replaceScene,
    setDiagnostics,
    setBrandCompatibilityReport,
    setPreflightResult,
    setExportResult,
    setWorkspaceMode
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
        operations: undoFrame.operations
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
        operations: redoFrame.operations
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
