import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Operation, Scene } from "@/engine/contracts";
import type { EditQueuePort } from "@/engine/editQueue";
import { useDocumentSync, type UseDocumentSyncDeps } from "@/hooks/useDocumentSync";

function sceneStub(title: string): Scene {
  return { meta: { title } } as unknown as Scene;
}

function makeDeps(overrides: Partial<UseDocumentSyncDeps>): {
  deps: UseDocumentSyncDeps;
  capturedLocalScene: () => Scene;
} {
  let localScene: (() => Scene) | null = null;
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
    capturedLocalScene: () => {
      if (!localScene) {
        throw new Error("edit queue was never created");
      }
      return localScene();
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
