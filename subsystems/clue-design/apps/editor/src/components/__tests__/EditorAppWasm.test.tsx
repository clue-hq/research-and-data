import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Operation, Scene } from "@/engine/contracts";
import type { ReconcileEvent } from "@/engine/editQueue";
import { WasmEngine } from "@/engine/wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";
import EditorApp from "../EditorApp";

/**
 * Track E W2: EditorApp running on the REAL WASM engine. The editor's
 * operation path, undo frames, and selectors must behave identically to
 * the legacy local engine — same UI flows, scene state owned by the wasm
 * module, undo frames working over engine snapshots.
 */

vi.mock("../canvas/CanvasSurface", () => ({
  CanvasSurface: ({
    scene,
    selectedNodeId
  }: {
    scene: Scene;
    selectedNodeId: string | null;
  }) =>
    React.createElement("div", {
      "data-testid": "canvas-selection",
      "data-selected-node": selectedNodeId ?? "",
      "data-selected-x": selectedNodeId
        ? String(scene.nodes[selectedNodeId]?.transform.x ?? "")
        : ""
    })
}));

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalSceneFixture)) as Scene;
}

describe.skipIf(!wasmArtifactPresent)("EditorApp on the WASM engine", () => {
  it("applies inspector operations through the engine and undoes over engine snapshots", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene();
    const engine = new WasmEngine(module, scene);

    render(
      <EditorApp initialScene={scene} initialSelectedNodeId={null} optimisticEngine={engine} />
    );

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "WASM-owned title" }
    });

    expect(screen.getByRole("heading", { name: "WASM-owned title" })).toBeInTheDocument();
    expect(screen.getAllByText(/update_document/).length).toBeGreaterThan(0);
    // The engine's wasm-side state agrees with the rendered snapshot.
    expect((JSON.parse(engine.sceneJson()) as Scene).meta.title).toBe("WASM-owned title");
    expect(engine.scene.meta.title).toBe("WASM-owned title");

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(
      screen.getByRole("heading", { name: scene.meta.title })
    ).toBeInTheDocument();
    // Undo frames reset the engine too (snapshot-in path).
    expect((JSON.parse(engine.sceneJson()) as Scene).meta.title).toBe(scene.meta.title);

    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(screen.getByRole("heading", { name: "WASM-owned title" })).toBeInTheDocument();
    expect((JSON.parse(engine.sceneJson()) as Scene).meta.title).toBe("WASM-owned title");
  });

  it("rejects engine-invalid operations with a diagnostic and an unchanged scene", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene();
    const engine = new WasmEngine(module, scene);

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId="node_contact_name"
        optimisticEngine={engine}
      />
    );

    // Lock the node, then try to nudge it with the keyboard: the legacy
    // path also rejects this, but here the rejection comes from lumen-core.
    fireEvent.click(screen.getByRole("button", { name: "Unlocked" }));
    expect(engine.scene.nodes.node_contact_name.locked).toBe(true);

    fireEvent.keyDown(window, { key: "ArrowRight" });
    // Locked node: nudge ignored, scene unchanged.
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(
      scene.nodes.node_contact_name.transform.x
    );
  });

  it("enqueues accepted batches for persistence and reconciles divergence", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene();
    const engine = new WasmEngine(module, scene);
    const enqueued: Operation[][] = [];
    let reconcile: ((event: ReconcileEvent) => void) | null = null;

    render(
      <EditorApp
        documentId="doc_w3"
        initialScene={scene}
        initialSelectedNodeId={null}
        optimisticEngine={engine}
        editQueueFactory={(options) => {
          reconcile = options.onReconcile;
          return {
            persistedBatches: 0,
            idle: async () => undefined,
            enqueueOperations: (operations) => {
              enqueued.push(operations);
            },
            resync: () => {}
          };
        }}
      />
    );

    fireEvent.change(screen.getByLabelText("Document Title"), {
      target: { value: "Persist me" }
    });

    // The locally-applied batch went to the queue (optimistic + enqueue).
    expect(enqueued).toHaveLength(1);
    expect(enqueued[0][0].kind).toBe("update_document");

    // Simulated server divergence: the authoritative scene replaces the
    // local one (engine included) and the diagnostic surfaces.
    const serverScene = cloneScene();
    serverScene.meta.title = "Server truth";
    const event: ReconcileEvent = {
      kind: "divergence",
      serverScene,
      serverVersion: 12,
      diagnostic: {
        severity: "error",
        phase: "operation",
        code: "EDITOR_WASM_RECONCILE_DIVERGENCE",
        message: "Optimistic scene diverged from the server after reconciliation.",
        subject: { kind: "document" },
        hint: null
      }
    };
    expect(reconcile).not.toBeNull();
    await waitFor(() => {
      reconcile?.(event);
      expect(screen.getByRole("heading", { name: "Server truth" })).toBeInTheDocument();
    });
    expect((JSON.parse(engine.sceneJson()) as Scene).meta.title).toBe("Server truth");
    expect(screen.getAllByText(/EDITOR_WASM_RECONCILE_DIVERGENCE/).length).toBeGreaterThan(0);
  });

  it("degrades to server-only mode when the module cannot load (W5)", async () => {
    // Flag on, no injected engine: the default runtime loader cannot
    // resolve /wasm/ in this environment, which is exactly the offline /
    // load-failure case. Editing must surface the server-only diagnostic
    // and leave the scene untouched, while server-backed flows keep
    // working.
    vi.stubEnv("NEXT_PUBLIC_LUMEN_WASM_CORE", "1");
    try {
      const scene = cloneScene();
      const preflightRunner = vi.fn().mockResolvedValue({
        status: "applied",
        scene,
        diagnostics: [],
        preflight: {
          has_errors: false,
          brand_ref_operations: 0,
          token_operations: 0,
          layout_operations: 0
        },
        brand_kit: { source: null }
      });
      render(
        <EditorApp
          initialScene={scene}
          initialSelectedNodeId={null}
          preflightRunner={preflightRunner}
        />
      );

      fireEvent.change(screen.getByLabelText("Document Title"), {
        target: { value: "No engine" }
      });

      expect(await screen.findByText(/EDITOR_SERVER_ONLY_MODE/)).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "No engine" })).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: scene.meta.title })).toBeInTheDocument();

      // Server-backed flows still work in server-only mode.
      fireEvent.click(screen.getByRole("button", { name: /Validate/ }));
      await waitFor(() => {
        expect(preflightRunner).toHaveBeenCalled();
      });
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("shows a loud canvas banner when the engine is expected but not active", async () => {
    // Flag on, no injected engine → the runtime loader can't resolve /wasm/
    // here (load_failure). The canvas is inert in server-only mode, so the
    // banner must appear and name the fix — never a silent, uneditable canvas.
    vi.stubEnv("NEXT_PUBLIC_LUMEN_WASM_CORE", "1");
    try {
      const scene = cloneScene();
      render(<EditorApp initialScene={scene} initialSelectedNodeId={null} />);

      const banner = await screen.findByTestId("engine-disabled-banner");
      expect(banner).toHaveTextContent(/Canvas editing is disabled/i);
      expect(banner).toHaveTextContent(/npm run build:wasm/);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("shows no engine banner when the WASM engine is active", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene();
    const engine = new WasmEngine(module, scene);

    render(
      <EditorApp initialScene={scene} initialSelectedNodeId={null} optimisticEngine={engine} />
    );

    expect(screen.queryByTestId("engine-disabled-banner")).toBeNull();
  });

  it("moves the selected node with arrow keys through the engine", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene();
    const engine = new WasmEngine(module, scene);
    const initialX = scene.nodes.node_contact_name.transform.x;

    render(
      <EditorApp
        initialScene={scene}
        initialSelectedNodeId="node_contact_name"
        optimisticEngine={engine}
      />
    );

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByTestId("canvas-selection")).toHaveAttribute(
      "data-selected-x",
      String(initialX + 1)
    );
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(initialX + 1);
    expect(
      (JSON.parse(engine.sceneJson()) as Scene).nodes.node_contact_name.transform.x
    ).toBe(initialX + 1);
  });
});
