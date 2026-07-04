import { useState, type Dispatch, type SetStateAction } from "react";
import type { AcceptedTurnRecord } from "@/components/AgentChatPanel";
import type { Diagnostic, Scene } from "@/engine/contracts";
import type { RevertOutcome } from "@/engine/documentStore";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";

/**
 * Per-turn Compare | Revert (2d).
 *
 * Compare is a read-only modal view: the engine is reset to the turn's
 * before/after snapshot (the CanvasKit surface paints from the ENGINE, so a
 * display-only setScene would show stale pixels), the live scene is parked,
 * and every mutation path is locked by EditorApp's compare guard until
 * "Back to current" restores it. Snapshots are session-local — a reload
 * loses Compare, while Revert still works off the persisted checkpoint.
 *
 * Revert calls the server (POST /documents/{id}/revert?checkpoint=…), which
 * unwinds every envelope AFTER the anchor via stored inverses — the turn
 * itself stays applied. On success the editor adopts the authoritative
 * scene, clears its local history (frames reference pre-revert states), and
 * re-arms the persistence queue's base_version. A refusal (anchor off the
 * active undo path — already reverted) is an honest outcome, not an error:
 * the checkpoint is marked invalid and the row renders disabled. Reverting
 * to a turn also invalidates every LATER turn's checkpoint — the client
 * mirror of the server's undo-stack rule.
 */
/** Compare is a read-only view of a past turn: mutations are locked from the
 * EditorApp orchestration layer with this diagnostic until "Back to current"
 * (the same two-sided-lock pattern as the agent-turn diagnostics). */
export const compareActiveDiagnostic = (): Diagnostic => ({
  severity: "warning",
  phase: "operation",
  code: "EDITOR_COMPARE_ACTIVE",
  message: "You're viewing a past turn — the canvas is read-only.",
  subject: { kind: "document" },
  hint: "Click \"Back to current\" to return to the live design before editing."
});

export interface UseTurnCheckpointsDeps {
  engineRef: { current: OptimisticEnginePort | null };
  sceneRef: { current: Scene };
  activeDocumentId: string | null;
  revertRunner: (documentId: string, checkpoint: string) => Promise<RevertOutcome>;
  setScene: Dispatch<SetStateAction<Scene>>;
  replaceScene: (nextScene: Scene) => void;
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
  /** Clears the local undo/redo history after adopting a reverted scene. */
  resetHistory: () => void;
  /** Re-arms the edit queue's base_version after the server-side write. */
  resyncPersistence: (version: number | null) => void;
  /** Posts a system message into the agent chat. */
  postSystemMessage: (content: string) => void;
  /** Checkpoints of all accepted turns in chat order — used to invalidate
   * every turn AFTER a successful revert target. */
  turnCheckpointsInOrder: () => string[];
}

export interface CompareView {
  /** The turn's stable client identity (AcceptedTurnRecord.key) — NOT the
   * checkpoint, which is null for non-revertible creation turns. */
  key: string;
  view: "before" | "after";
}

export function useTurnCheckpoints(deps: UseTurnCheckpointsDeps) {
  const {
    engineRef,
    sceneRef,
    activeDocumentId,
    revertRunner,
    setScene,
    replaceScene,
    setDiagnostics,
    resetHistory,
    resyncPersistence,
    postSystemMessage,
    turnCheckpointsInOrder
  } = deps;

  const [compare, setCompare] = useState<{
    key: string;
    record: AcceptedTurnRecord;
    view: "before" | "after";
    /** The live scene parked while the snapshot is displayed. */
    savedScene: Scene;
  } | null>(null);
  const [invalidCheckpoints, setInvalidCheckpoints] = useState<Set<string>>(new Set());
  const [isReverting, setIsReverting] = useState(false);

  const showSnapshot = (snapshot: Scene) => {
    const engine = engineRef.current;
    if (engine) {
      engine.reset(snapshot);
      setScene(engine.scene);
    } else {
      setScene(snapshot);
    }
  };

  /** Enter (or re-enter) compare for a turn. EditorApp guards ensure this is
   * only reachable while idle (no run, no pending review). */
  const startCompare = (record: AcceptedTurnRecord, view: "before" | "after") => {
    setCompare((current) => {
      const savedScene = current ? current.savedScene : sceneRef.current;
      showSnapshot(view === "before" ? record.beforeScene : record.afterScene);
      return { key: record.key, record, view, savedScene };
    });
  };

  const setCompareView = (view: "before" | "after") => {
    setCompare((current) => {
      if (!current || current.view === view) {
        return current;
      }
      showSnapshot(view === "before" ? current.record.beforeScene : current.record.afterScene);
      return { ...current, view };
    });
  };

  /** Exit compare and restore the live scene exactly as parked. */
  const exitCompare = () => {
    setCompare((current) => {
      if (current) {
        showSnapshot(current.savedScene);
      }
      return null;
    });
  };

  const revertToTurn = async (record: AcceptedTurnRecord) => {
    if (isReverting || compare) {
      return;
    }
    const checkpoint = record.checkpoint;
    if (!activeDocumentId || checkpoint === null) {
      // No persisted anchor — the turn's batch never got a server envelope
      // (the empty-canvas Accept whose creation IS the persistence). The
      // row normally never offers Revert for these; keep the refusal
      // honest and visible if it is reached anyway.
      postSystemMessage(
        "This turn can't be reverted — it created the document, so there is no earlier server state to unwind to."
      );
      setDiagnostics([
        {
          severity: "warning",
          phase: "operation",
          code: "EDITOR_REVERT_UNAVAILABLE",
          message: "This turn has no server checkpoint to revert to.",
          subject: { kind: "document" },
          hint: "Turns accepted before the document existed cannot be reverted."
        }
      ]);
      return;
    }
    setIsReverting(true);
    try {
      const outcome = await revertRunner(activeDocumentId, checkpoint);
      if (outcome.status === "refused") {
        markInvalid([checkpoint]);
        // The diagnostics panel may not be visible in agent mode — refusals
        // must land in the chat the user is looking at.
        postSystemMessage(`Couldn't revert this turn: ${outcome.message}`);
        setDiagnostics([
          {
            severity: "warning",
            phase: "operation",
            code: "EDITOR_REVERT_REFUSED",
            message: `The server refused the revert: ${outcome.message}`,
            subject: { kind: "document" },
            hint: "The checkpoint is no longer on the active history path (it may already be reverted)."
          }
        ]);
        return;
      }
      // Adopt the authoritative reverted scene; the local undo/redo frames
      // reference pre-revert states and are cleared, and the persistence
      // queue re-arms on the new server version.
      replaceScene(outcome.scene);
      resetHistory();
      resyncPersistence(outcome.currentVersion);
      // Every turn accepted AFTER the target left the active undo path.
      const ordered = turnCheckpointsInOrder();
      const anchorIndex = ordered.indexOf(checkpoint);
      markInvalid(anchorIndex >= 0 ? ordered.slice(anchorIndex + 1) : []);
      postSystemMessage(
        `Reverted the design to just after this turn (${outcome.revertedBatchIds.length} later change batch${outcome.revertedBatchIds.length === 1 ? "" : "es"} undone).`
      );
      setDiagnostics([]);
    } catch (error) {
      // Visible in the chat too — the diagnostics panel may be hidden.
      postSystemMessage(
        "Reverting failed — the document is unchanged. Check the API connection and retry."
      );
      setDiagnostics([
        {
          severity: "error",
          phase: "operation",
          code: "EDITOR_REVERT_FAILED",
          message:
            error instanceof Error
              ? `Reverting to the checkpoint failed: ${error.message}`
              : "Reverting to the checkpoint failed.",
          subject: { kind: "document" },
          hint: "The document is unchanged. Check the API connection and retry."
        }
      ]);
    } finally {
      setIsReverting(false);
    }
  };

  const markInvalid = (checkpoints: string[]) => {
    if (checkpoints.length === 0) {
      return;
    }
    setInvalidCheckpoints((current) => {
      const next = new Set(current);
      for (const checkpoint of checkpoints) {
        next.add(checkpoint);
      }
      return next;
    });
  };

  const compareView: CompareView | null = compare
    ? { key: compare.key, view: compare.view }
    : null;

  return {
    compareView,
    invalidCheckpoints,
    isReverting,
    startCompare,
    setCompareView,
    exitCompare,
    revertToTurn
  };
}
