import { renderHook } from "@testing-library/react";
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

  it("mirrors the selection set as chips with fresh layer names", () => {
    const { result } = renderHook(() => useTargetChips(scene, ["node_a", "node_b"]));
    expect(result.current.chips).toEqual([
      { id: "node_a", name: "Headline" },
      { id: "node_b", name: "Subtitle" }
    ]);
    expect(result.current.targetNodeIds).toEqual(["node_a", "node_b"]);
  });

  it("is empty when nothing is selected", () => {
    const { result } = renderHook(() => useTargetChips(scene, []));
    expect(result.current.chips).toEqual([]);
    expect(result.current.targetNodeIds).toEqual([]);
  });

  it("falls back to the node id when a node has no name", () => {
    const nameless = sceneWithNodes({ node_x: "" });
    const { result } = renderHook(() => useTargetChips(nameless, ["node_x"]));
    // Empty string is falsy → id shown.
    expect(result.current.chips[0].name).toBe("node_x");
  });
});
