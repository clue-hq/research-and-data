import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { Diagnostic, Operation, Scene } from "@/engine/contracts";
import type { CreatedDocument } from "@/engine/documentStore";
import type { EditQueuePort, ReconcileEvent } from "@/engine/editQueue";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import type { EditorHistoryFrame } from "@/hooks/useEditHistory";

export type EditQueueFactory = (options: {
  documentId: string;
  localScene: () => Scene;
  onReconcile: (event: ReconcileEvent) => void;
}) => EditQueuePort;

/**
 * Document identity + the persistence leg: which server document this canvas
 * IS (auto-created at the first persisting action — every canvas is a doc),
 * and the ordered edit queue that ships committed batches to
 * /documents/{id}/operations with reconcile-at-drain.
 *
 * The adoption invariant lives here: when the server mints a real id, every
 * local copy of the scene (engine, React state, undo/redo frames) must switch
 * to it in the same breath — missing any one of the three flags a false
 * reconcile divergence on `meta.id`.
 *
 * Deps are rebuilt every render (same closure semantics as the inline
 * originals) — never memoize the object.
 */
export interface UseDocumentSyncDeps {
  /** The document id the editor was mounted with (loader path), if any. */
  documentId?: string;
  documentCreator: (scene: Scene) => Promise<CreatedDocument>;
  editQueueFactory: EditQueueFactory;
  engineRef: { current: OptimisticEnginePort | null };
  sceneRef: { current: Scene };
  replaceScene: (nextScene: Scene) => void;
  setScene: Dispatch<SetStateAction<Scene>>;
  setDiagnostics: Dispatch<SetStateAction<Diagnostic[]>>;
  /** Clears a STICKY diagnostic once its condition is resolved (the sticky
   * merge policy deliberately ignores ordinary overwrites). */
  resolveDiagnosticCode: (code: string) => void;
  setUndoStack: Dispatch<SetStateAction<EditorHistoryFrame[]>>;
  setRedoStack: Dispatch<SetStateAction<EditorHistoryFrame[]>>;
}

export function useDocumentSync(deps: UseDocumentSyncDeps) {
  const {
    documentId,
    documentCreator,
    editQueueFactory,
    engineRef,
    sceneRef,
    replaceScene,
    setScene,
    setDiagnostics,
    resolveDiagnosticCode,
    setUndoStack,
    setRedoStack
  } = deps;

  // Document identity is state, not just a prop — an unsaved canvas adopts a
  // server-minted id at its first persisting action (auto-create).
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(documentId ?? null);
  const activeDocumentIdRef = useRef<string | null>(activeDocumentId);
  activeDocumentIdRef.current = activeDocumentId;
  const documentCreationRef = useRef<Promise<string | null> | null>(null);

  // W3 optimistic pipeline: locally-applied batches persist to the
  // document API in order; the server reconciles at drain. Divergence is a
  // bug signal — the server scene replaces the local one and a diagnostic
  // surfaces.
  const editQueueRef = useRef<EditQueuePort | null>(null);
  const ensureEditQueue = (queueDocumentId: string): EditQueuePort => {
    editQueueRef.current ??= editQueueFactory({
      documentId: queueDocumentId,
      localScene: () => engineRef.current?.scene ?? sceneRef.current,
      onReconcile: (event) => {
        if (event.serverScene) {
          replaceScene(event.serverScene);
        }
        setDiagnostics([event.diagnostic]);
      }
    });
    return editQueueRef.current;
  };

  /**
   * Adopt a freshly-created document id. Local scenes carry the shared
   * `doc_untitled` placeholder id; the server minted the real one, so
   * every local copy of the scene (engine, React state, undo/redo frames)
   * must switch to it — otherwise the first persistence reconcile flags a
   * false divergence on `meta.id`. The URL gains `?document=<id>` so a
   * reload reopens this document.
   */
  const adoptCreatedDocument = (newDocumentId: string) => {
    const patchSceneId = (input: Scene): Scene => ({
      ...input,
      meta: { ...input.meta, id: newDocumentId }
    });
    activeDocumentIdRef.current = newDocumentId;
    setActiveDocumentId(newDocumentId);
    const engine = engineRef.current;
    if (engine) {
      engine.reset(patchSceneId(engine.scene));
      setScene(engine.scene);
    } else {
      setScene((current) => patchSceneId(current));
    }
    setUndoStack((stack) => stack.map((frame) => ({ ...frame, scene: patchSceneId(frame.scene) })));
    setRedoStack((stack) => stack.map((frame) => ({ ...frame, scene: patchSceneId(frame.scene) })));
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("document", newDocumentId);
      window.history.replaceState(null, "", url);
    }
  };

  const enqueueForPersistence = (
    previousScene: Scene,
    operations: Operation[],
    nextScene: Scene
  ) => {
    const engine = engineRef.current;
    if (!engine || engine.kind !== "wasm") {
      return;
    }
    const existingDocumentId = activeDocumentIdRef.current;
    if (existingDocumentId) {
      ensureEditQueue(existingDocumentId).enqueueOperations(operations);
      return;
    }
    // Auto-create: the first persisting action turns this canvas into a
    // document. Batches that land while creation is in flight ride behind it
    // in order.
    if (documentCreationRef.current) {
      documentCreationRef.current = documentCreationRef.current.then((createdId) => {
        if (createdId) {
          ensureEditQueue(createdId).enqueueOperations(operations);
        }
        return createdId;
      });
      return;
    }
    // An empty canvas is not a creatable document (LUMV0100: a scene needs at
    // least one page); seed from the post-op scene instead and skip
    // enqueueing the triggering batch — for that case the creation IS its
    // persistence. If even the post-op scene is still empty (say, a title
    // edit before any artboard exists), stay local: the scene carries those
    // changes into the eventual creation seed.
    const seedFromPrevious = Object.keys(previousScene.pages).length > 0;
    const seedScene = seedFromPrevious ? previousScene : nextScene;
    if (Object.keys(seedScene.pages).length === 0) {
      return;
    }
    documentCreationRef.current = documentCreator(seedScene)
      .then((created) => {
        adoptCreatedDocument(created.documentId);
        // A retry succeeded — the sticky create-failure is resolved.
        resolveDiagnosticCode("EDITOR_DOCUMENT_CREATE_FAILED");
        if (seedFromPrevious) {
          ensureEditQueue(created.documentId).enqueueOperations(operations);
        }
        return created.documentId;
      })
      .catch((error: unknown) => {
        // Editing continues locally; the next persisting action retries.
        documentCreationRef.current = null;
        setDiagnostics([
          {
            severity: "error",
            phase: "operation",
            code: "EDITOR_DOCUMENT_CREATE_FAILED",
            message:
              error instanceof Error
                ? `Creating a document for this design failed: ${error.message}`
                : "Creating a document for this design failed.",
            subject: { kind: "document" },
            hint: "Local editing continues, but nothing is persisted yet. Check the API connection — the next edit retries."
          }
        ]);
        return null;
      });
  };

  return {
    activeDocumentId,
    enqueueForPersistence
  };
}
