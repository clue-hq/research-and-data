import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Scene } from "@/engine/contracts";
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
