import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Diagnostic, Operation, Scene } from "@/engine/contracts";
import type { EditQueuePort, ReconcileEvent } from "@/engine/editQueue";
import { useDocumentSync, type UseDocumentSyncDeps } from "@/hooks/useDocumentSync";

function sceneStub(title: string): Scene {
  return { meta: { title } } as unknown as Scene;
}

function makeDeps(overrides: Partial<UseDocumentSyncDeps>): {
  deps: UseDocumentSyncDeps;
  capturedLocalScene: () => Scene;
  triggerReconcile: (event: ReconcileEvent) => void;
  queue: EditQueuePort;
} {
  let localScene: (() => Scene) | null = null;
  let onReconcile: ((event: ReconcileEvent) => void) | null = null;
  const queue: EditQueuePort = {
    enqueueOperations: vi.fn(),
    idle: () => Promise.resolve(),
    persistedBatches: 0,
    resync: vi.fn()
  };
  const deps: UseDocumentSyncDeps = {
    documentId: "doc_test",
    documentCreator: vi.fn(),
    editQueueFactory: (options) => {
      localScene = options.localScene;
      onReconcile = options.onReconcile;
      return queue;
    },
    engineRef: { current: null },
    sceneRef: { current: sceneStub("react-state") },
    previewBaseSceneRef: { current: null },
    replaceScene: vi.fn(),
    setScene: vi.fn(),
    setDiagnostics: vi.fn(),
    resolveDiagnosticCode: vi.fn(),
    setUndoStack: vi.fn(),
    setRedoStack: vi.fn(),
    ...overrides
  };
  return {
    deps,
    queue,
    capturedLocalScene: () => {
      if (!localScene) {
        throw new Error("edit queue was never created");
      }
      return localScene();
    },
    triggerReconcile: (event) => {
      if (!onReconcile) {
        throw new Error("edit queue was never created");
      }
      onReconcile(event);
    }
  };
}

describe("useDocumentSync reconcile baseline", () => {
  it("compares against the preview base scene while an agent draft is pending", () => {
    const previewBase = sceneStub("pre-draft");
    const draftLaden = sceneStub("draft-applied");
    const { deps, capturedLocalScene } = makeDeps({
      engineRef: { current: { kind: "wasm", scene: draftLaden } as never },
      previewBaseSceneRef: { current: previewBase }
    });
    const { result } = renderHook(() => useDocumentSync(deps));
    // Force queue creation through the persistence path.
    result.current.enqueueForPersistence(
      previewBase,
      [{ kind: "remove_node", node_id: "n" } as unknown as Operation],
      draftLaden
    );

    // A pending draft's ops live in the optimistic engine but in no enqueued
    // batch — reconciling against the engine scene would flag divergence and
    // clobber the draft with the server state (the user-hit revert).
    expect(capturedLocalScene()).toBe(previewBase);
  });

  it("compares against the live engine scene when no draft is pending", () => {
    const engineScene = sceneStub("engine");
    const { deps, capturedLocalScene } = makeDeps({
      engineRef: { current: { kind: "wasm", scene: engineScene } as never },
      previewBaseSceneRef: { current: null }
    });
    const { result } = renderHook(() => useDocumentSync(deps));
    result.current.enqueueForPersistence(
      engineScene,
      [{ kind: "remove_node", node_id: "n" } as unknown as Operation],
      engineScene
    );

    expect(capturedLocalScene()).toBe(engineScene);
  });
});

describe("useDocumentSync 409-safe reconcile", () => {
  const rejectedEvent = (): ReconcileEvent => ({
    kind: "rejected",
    serverScene: sceneStub("server-authoritative"),
    serverVersion: 42,
    diagnostic: {
      severity: "error",
      phase: "operation",
      code: "EDITOR_WASM_EDIT_REJECTED",
      message: "The server rejected a persisted edit batch (409).",
      subject: { kind: "document" },
      hint: "The local scene has been replaced by the server's authoritative state."
    } as Diagnostic
  });

  it("adopts the server scene, clears both history stacks, and re-arms base_version on a rejected batch (the undo-after-accept 409 desync)", () => {
    const engineScene = sceneStub("engine");
    const setUndoStack = vi.fn();
    const setRedoStack = vi.fn();
    const replaceScene = vi.fn();
    const setDiagnostics = vi.fn();
    const { deps, queue, triggerReconcile } = makeDeps({
      engineRef: { current: { kind: "wasm", scene: engineScene } as never },
      setUndoStack,
      setRedoStack,
      replaceScene,
      setDiagnostics
    });
    const { result } = renderHook(() => useDocumentSync(deps));
    // Create the queue (and capture its onReconcile) through the persist path.
    result.current.enqueueForPersistence(
      engineScene,
      [{ kind: "remove_node", node_id: "n" } as unknown as Operation],
      engineScene
    );

    triggerReconcile(rejectedEvent());

    // Server state adopted, both local stacks dropped (no stale frame to pop),
    // and the queue's base_version re-armed to the server's — so the very next
    // edit is not rejected in turn. This is the fix for the local/server undo
    // desync: a failed server undo/redo never leaves a mutated local stack.
    expect(replaceScene).toHaveBeenCalledWith(rejectedEvent().serverScene);
    expect(setUndoStack).toHaveBeenCalledWith([]);
    expect(setRedoStack).toHaveBeenCalledWith([]);
    expect(queue.resync).toHaveBeenCalledWith(42);
    expect(setDiagnostics).toHaveBeenCalledWith([rejectedEvent().diagnostic]);
  });

  it("leaves the history stacks untouched when a reconcile event carries no server scene", () => {
    const engineScene = sceneStub("engine");
    const setUndoStack = vi.fn();
    const setRedoStack = vi.fn();
    const { deps, queue, triggerReconcile } = makeDeps({
      engineRef: { current: { kind: "wasm", scene: engineScene } as never },
      setUndoStack,
      setRedoStack
    });
    const { result } = renderHook(() => useDocumentSync(deps));
    result.current.enqueueForPersistence(
      engineScene,
      [{ kind: "remove_node", node_id: "n" } as unknown as Operation],
      engineScene
    );

    triggerReconcile({
      kind: "request_failed",
      serverScene: null,
      serverVersion: null,
      diagnostic: {
        severity: "error",
        phase: "operation",
        code: "EDITOR_WASM_EDIT_PERSIST_FAILED",
        message: "Persisting edits to the server failed.",
        subject: { kind: "document" },
        hint: "Local optimistic edits continue."
      } as Diagnostic
    });

    // No authoritative scene was recovered, so the local state stands: don't
    // wipe the user's history on a transient transport failure.
    expect(setUndoStack).not.toHaveBeenCalled();
    expect(setRedoStack).not.toHaveBeenCalled();
    expect(queue.resync).not.toHaveBeenCalled();
  });
});
