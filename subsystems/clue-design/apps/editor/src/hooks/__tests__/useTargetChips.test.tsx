import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Node, Scene } from "@/engine/contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { useTargetChips } from "../useTargetChips";

function sceneWithNodes(names: Record<string, string>): Scene {
  const base = minimalScene;
  const nodes: Record<string, Node> = {};
  for (const [id, name] of Object.entries(names)) {
    nodes[id] = { ...(Object.values(base.nodes)[0] as Node), id, name };
  }
  return { ...base, nodes };
}

describe("useTargetChips", () => {
  const scene = sceneWithNodes({ node_a: "Headline", node_b: "Subtitle" });

  it("adds the selected node as a chip and keeps it after deselect", () => {
    const { result, rerender } = renderHook(
      ({ selected }) => useTargetChips(scene, selected),
      { initialProps: { selected: "node_a" as string | null } }
    );
    expect(result.current.chips).toEqual([{ id: "node_a", name: "Headline" }]);
    expect(result.current.targetNodeIds).toEqual(["node_a"]);

    // Deselecting must NOT drop the chip — the target set persists.
    rerender({ selected: null });
    expect(result.current.targetNodeIds).toEqual(["node_a"]);
  });

  it("accumulates multiple targets and dedupes re-selection", () => {
    const { result, rerender } = renderHook(
      ({ selected }) => useTargetChips(scene, selected),
      { initialProps: { selected: "node_a" as string | null } }
    );
    rerender({ selected: "node_b" });
    rerender({ selected: "node_a" }); // already chipped — no duplicate
    expect(result.current.targetNodeIds).toEqual(["node_a", "node_b"]);
  });

  it("removes and clears chips", () => {
    const { result } = renderHook(() => useTargetChips(scene, "node_a"));
    act(() => result.current.removeChip("node_a"));
    expect(result.current.targetNodeIds).toEqual([]);
  });

  it("prunes a chip whose node was deleted from the scene", () => {
    const { result, rerender } = renderHook(
      ({ currentScene }) => useTargetChips(currentScene, "node_a"),
      { initialProps: { currentScene: scene } }
    );
    expect(result.current.targetNodeIds).toEqual(["node_a"]);
    // node_a no longer exists → its chip is dropped.
    rerender({ currentScene: sceneWithNodes({ node_b: "Subtitle" }) });
    expect(result.current.targetNodeIds).toEqual([]);
  });
});
