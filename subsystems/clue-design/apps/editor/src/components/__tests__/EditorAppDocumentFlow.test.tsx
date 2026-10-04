import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import { emptyScene } from "@/fixtures/emptyScene";
import type { Operation, Scene } from "@/engine/contracts";
import type { EditorAgentResult, EditorAgentRunner } from "@/engine/agentRunner";
import type { CreatedDocument } from "@/engine/documentStore";
import type { EditQueuePort } from "@/engine/editQueue";
import { addPage, updateDocumentTitle } from "@/engine/operations";
import { WasmEngine, type WasmModule } from "@/engine/wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";
import EditorApp, { type EditQueueFactory } from "../EditorApp";

/**
 * Phase 2a: document identity + exclusive turns + message queue.
 *
 * - Auto-create: with no documentId, the first persisting action creates a
 *   document (Moda's "every canvas is a doc"), the editor adopts the
 *   server-minted id everywhere (scene, undo frames, URL), and persistence
 *   flows through the ordinary edit queue.
 * - Turn lock: while the agent designs, canvas mutations are blocked.
 * - Queue: messages typed while busy wait and drain one per idle transition.
 */

// CanvasKit cannot load under Node/jsdom (no /canvaskit/canvaskit.wasm). loadCanvasKit already
// catches the failed init, but Emscripten's abort also rejects an internal promise nobody awaits,
// and that unhandled rejection failed this suite's CI run even with every test passing
// (Editor checks, red since at least 2026-09-22). Resolve to `null` — the documented
// "CanvasKit unavailable, stay on Konva" path — and keep the module's other exports real.
vi.mock("@/engine/canvaskit/loadCanvasKit", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/engine/canvaskit/loadCanvasKit")>()),
  loadCanvasKit: vi.fn().mockResolvedValue(null)
}));

vi.mock("../canvas/CanvasSurface", () => ({
  CanvasSurface: ({ selectedNodeId }: { selectedNodeId: string | null }) =>
    React.createElement("div", {
      "data-testid": "canvas-selection",
      "data-selected-node": selectedNodeId ?? ""
    })
}));

let wasmModule: WasmModule;

function cloneMinimalScene(): Scene {
  return JSON.parse(JSON.stringify(minimalSceneFixture)) as Scene;
}

function cloneEmptyScene(): Scene {
  return JSON.parse(JSON.stringify(emptyScene)) as Scene;
}

type DebugWindow = typeof window & {
  __lumenEditorDebug?: {
    applyOperations: (operations: Operation[]) => void;
    getScene: () => Scene;
    getEngineScene: () => Scene | null;
  };
};

function editorDebug() {
  const debug = (window as DebugWindow).__lumenEditorDebug;
  if (!debug) {
    throw new Error("editor debug hook not installed");
  }
  return debug;
}

function recordingEditQueueFactory(): {
  factory: EditQueueFactory;
  createdFor: string[];
  batches: Operation[][];
} {
  const createdFor: string[] = [];
  const batches: Operation[][] = [];
  const factory: EditQueueFactory = (options) => {
    createdFor.push(options.documentId);
    const queue: EditQueuePort = {
      enqueueOperations: (operations) => {
        batches.push(operations);
      },
      idle: () => Promise.resolve(),
      persistedBatches: 0,
      resync: () => {}
    };
    return queue;
  };
  return { factory, createdFor, batches };
}

function testPage(id: string) {
  return {
    id,
    name: "Concept",
    size: {
      width: 1080,
      height: 1080,
      unit: "px" as const,
      preset: null,
      orientation: "portrait" as const
    },
    children: [],
    bleed: null,
    safe_area: null,
    background: []
  };
}

function failedTurn(summary: string): EditorAgentResult {
  return {
    status: "failed",
    summary,
    dsl_blocks: [],
    operations: [],
    draft_scene: null,
    stop_reason: "max_iterations",
    acceptance_scope: null,
    diagnostics: [],
    trace: { run_id: "run_test", trace_dir: null, preview_paths: [] },
    artifacts: []
  };
}

function proposedTurn(operations: Operation[]): EditorAgentResult {
  return {
    status: "proposed",
    summary: "Proposed a change.",
    dsl_blocks: [],
    operations,
    draft_scene: null,
    stop_reason: "edit_scoped_acceptance",
    acceptance_scope: "edit",
    diagnostics: [],
    trace: { run_id: "run_test", trace_dir: null, preview_paths: [] },
    artifacts: []
  };
}

function openAgentPanel() {
  fireEvent.click(screen.getByRole("button", { name: /^Agent$/i }));
}

/** The topbar Undo (the HistoryPanel renders its own once a document exists). */
function toolbarUndoButton() {
  return within(screen.getByLabelText("Editing tools")).getByRole("button", {
    name: /^Undo$/i
  });
}

function sendAgentMessage(prompt: string) {
  fireEvent.change(screen.getByLabelText("Message the agent"), {
    target: { value: prompt }
  });
  fireEvent.click(screen.getByRole("button", { name: /^(Send|Queue)$/i }));
}

describe.skipIf(!wasmArtifactPresent)("EditorApp Phase 2a document flow", () => {
  beforeAll(async () => {
    wasmModule = await loadWasmModuleFromDisk();
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("auto-creates a document at the first persisting action and adopts the server id everywhere", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    const { factory, createdFor, batches } = recordingEditQueueFactory();
    const documentCreator = vi
      .fn<(scene: Scene) => Promise<CreatedDocument>>()
      .mockResolvedValue({ documentId: "doc_created_1" });

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        editQueueFactory={factory}
        documentCreator={documentCreator}
      />
    );

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "Renamed by human" }
    });

    await waitFor(() => {
      expect(createdFor).toEqual(["doc_created_1"]);
    });
    // The creation seed is the PRE-op scene, so the triggering batch gets its
    // own server-side envelope (undo/checkpoint machinery for turn 1).
    expect(documentCreator).toHaveBeenCalledTimes(1);
    expect(documentCreator.mock.calls[0][0].meta.title).toBe("Hospital Letter");
    expect(batches).toHaveLength(1);
    expect(batches[0][0].kind).toBe("update_document");
    // Identity adopted: engine scene, URL.
    expect(engine.scene.meta.id).toBe("doc_created_1");
    expect(window.location.search).toContain("document=doc_created_1");

    // Undo frames were patched too: undoing restores the old title but keeps
    // the adopted document id (otherwise the next reconcile would flag a
    // false meta.id divergence).
    fireEvent.click(toolbarUndoButton());
    expect(engine.scene.meta.title).toBe("Hospital Letter");
    expect(engine.scene.meta.id).toBe("doc_created_1");
  });

  it("creates from the post-op scene when the canvas starts empty and skips the triggering batch", async () => {
    const scene = cloneEmptyScene();
    const engine = new WasmEngine(wasmModule, scene);
    const { factory, createdFor, batches } = recordingEditQueueFactory();
    const documentCreator = vi
      .fn<(scene: Scene) => Promise<CreatedDocument>>()
      .mockResolvedValue({ documentId: "doc_created_2" });

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        editQueueFactory={factory}
        documentCreator={documentCreator}
      />
    );

    act(() => {
      editorDebug().applyOperations([addPage(testPage("page_first"))]);
    });

    await waitFor(() => {
      expect(documentCreator).toHaveBeenCalledTimes(1);
    });
    // An empty scene cannot be created (LUMV0100), so the seed is the
    // post-op scene and the triggering batch is NOT double-persisted.
    expect(Object.keys(documentCreator.mock.calls[0][0].pages)).toEqual(["page_first"]);
    expect(batches).toHaveLength(0);
    await waitFor(() => {
      expect(engine.scene.meta.id).toBe("doc_created_2");
    });

    // The next edit persists through the ordinary queue under the new id.
    act(() => {
      editorDebug().applyOperations([updateDocumentTitle("After creation")]);
    });
    expect(createdFor).toEqual(["doc_created_2"]);
    expect(batches).toHaveLength(1);
    expect(batches[0][0].kind).toBe("update_document");
    expect(documentCreator).toHaveBeenCalledTimes(1);
  });

  it("persists local undo as the inverse batch and redo as the original batch", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    const { factory, batches } = recordingEditQueueFactory();
    const documentCreator = vi
      .fn<(scene: Scene) => Promise<CreatedDocument>>()
      .mockResolvedValue({ documentId: "doc_history_1" });

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        editQueueFactory={factory}
        documentCreator={documentCreator}
      />
    );

    act(() => {
      editorDebug().applyOperations([updateDocumentTitle("Persisted title")]);
    });
    await waitFor(() => {
      expect(engine.scene.meta.id).toBe("doc_history_1");
    });
    expect(batches).toHaveLength(1);

    // Undo posts the engine-computed INVERSE batch — the server document
    // follows local history instead of drifting until the next reconcile.
    fireEvent.click(toolbarUndoButton());
    expect(engine.scene.meta.title).toBe("Hospital Letter");
    expect(batches).toHaveLength(2);
    expect(batches[1][0].kind).toBe("update_document");
    expect(JSON.stringify(batches[1])).toContain("Hospital Letter");

    // Redo re-posts the original batch (history stays append-only).
    fireEvent.click(
      within(screen.getByLabelText("Editing tools")).getByRole("button", {
        name: /^Redo$/i
      })
    );
    expect(engine.scene.meta.title).toBe("Persisted title");
    expect(batches).toHaveLength(3);
    expect(JSON.stringify(batches[2])).toContain("Persisted title");
  });

  it("keeps edits local when creation fails and retries on the next persisting action", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    const { factory, batches } = recordingEditQueueFactory();
    const documentCreator = vi
      .fn<(scene: Scene) => Promise<CreatedDocument>>()
      .mockRejectedValueOnce(new Error("api down"))
      .mockResolvedValue({ documentId: "doc_created_3" });

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        editQueueFactory={factory}
        documentCreator={documentCreator}
      />
    );

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "First attempt" }
    });
    expect(
      (await (async () => {
        fireEvent.click(screen.getByRole("button", { name: /^diagnostics panel$/i }));
        return screen.findAllByText(/Creating a document for this design failed/);
      })()).length
    ).toBeGreaterThan(0);
    expect(engine.scene.meta.title).toBe("First attempt");
    expect(batches).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /^Inspect$/i }));
    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "Second attempt" }
    });
    await waitFor(() => {
      expect(engine.scene.meta.id).toBe("doc_created_3");
    });
    expect(documentCreator).toHaveBeenCalledTimes(2);
    // Only the retrying batch persists; the failed one is carried by the
    // creation seed (the second call's seed already has the first title).
    expect(documentCreator.mock.calls[1][0].meta.title).toBe("First attempt");
    expect(batches).toHaveLength(1);
  });

  it("locks canvas mutations while a turn runs and unlocks after it settles", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    let resolveTurn!: (result: EditorAgentResult) => void;
    const agentRunner: EditorAgentRunner = vi.fn(
      () =>
        new Promise<EditorAgentResult>((resolve) => {
          resolveTurn = resolve;
        })
    );

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        agentRunner={agentRunner}
      />
    );

    openAgentPanel();
    sendAgentMessage("Design something");
    expect(await screen.findByTestId("agent-designing-banner")).toBeInTheDocument();

    // Mutations are blocked while the agent designs (Moda's exclusive turn).
    act(() => {
      editorDebug().applyOperations([updateDocumentTitle("Sneaky edit")]);
    });
    expect(engine.scene.meta.title).toBe("Hospital Letter");
    // The blocked edit surfaced a diagnostic (the agent panel shows the
    // count strip; the message renders in the Diagnostics panel).
    expect(screen.getByText("1 diagnostic")).toBeInTheDocument();
    expect(toolbarUndoButton()).toBeDisabled();

    await act(async () => {
      resolveTurn(failedTurn("Nothing to apply."));
    });
    await waitFor(() => {
      expect(screen.queryByTestId("agent-designing-banner")).not.toBeInTheDocument();
    });

    // The canvas is editable again.
    act(() => {
      editorDebug().applyOperations([updateDocumentTitle("After the turn")]);
    });
    expect(engine.scene.meta.title).toBe("After the turn");
  });

  it("queues messages during a run and drains one per idle transition", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    const turnResolvers: Array<(result: EditorAgentResult) => void> = [];
    const agentRunner: EditorAgentRunner = vi.fn(
      () =>
        new Promise<EditorAgentResult>((resolve) => {
          turnResolvers.push(resolve);
        })
    );

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        agentRunner={agentRunner}
      />
    );

    openAgentPanel();
    sendAgentMessage("First request");
    expect(await screen.findByTestId("agent-designing-banner")).toBeInTheDocument();

    // While running, the composer queues instead of sending.
    sendAgentMessage("Second request");
    sendAgentMessage("Third request");
    expect(agentRunner).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Queued messages")).toBeInTheDocument();
    expect(screen.getByText("Second request")).toBeInTheDocument();
    expect(screen.getByText("Third request")).toBeInTheDocument();

    // A queued message can be removed before it runs.
    fireEvent.click(
      screen.getByRole("button", { name: "Remove queued message: Second request" })
    );
    expect(screen.queryByText("Second request")).not.toBeInTheDocument();

    // The turn settles → exactly one queued message drains as the next turn.
    await act(async () => {
      turnResolvers[0](failedTurn("Turn one finished."));
    });
    await waitFor(() => {
      expect(agentRunner).toHaveBeenCalledTimes(2);
    });
    expect(agentRunner).toHaveBeenLastCalledWith(
      expect.objectContaining({ prompt: "Third request" })
    );
    expect(screen.queryByLabelText("Queued messages")).not.toBeInTheDocument();
  });

  it("holds queued messages through a pending review and drains after Reject", async () => {
    const scene = cloneMinimalScene();
    const engine = new WasmEngine(wasmModule, scene);
    const results: Array<Promise<EditorAgentResult>> = [
      Promise.resolve(proposedTurn([updateDocumentTitle("Agent title")])),
      new Promise<EditorAgentResult>(() => {})
    ];
    const agentRunner: EditorAgentRunner = vi.fn(() => results.shift()!);

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        agentRunner={agentRunner}
      />
    );

    openAgentPanel();
    sendAgentMessage("Change the title");
    expect(await screen.findByText("Reviewing changes")).toBeInTheDocument();

    // Queue during review; nothing drains while the preview is pending.
    sendAgentMessage("Follow-up request");
    expect(agentRunner).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Follow-up request")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("toolbar", { name: "Review agent changes" }).querySelector("button.agent-review-reject") as HTMLButtonElement
    );
    await waitFor(() => {
      expect(agentRunner).toHaveBeenCalledTimes(2);
    });
    expect(agentRunner).toHaveBeenLastCalledWith(
      expect.objectContaining({ prompt: "Follow-up request" })
    );
    // Reject restored the base scene before the queued turn seeded.
    expect(engine.scene.meta.title).toBe("Hospital Letter");
  });
});
