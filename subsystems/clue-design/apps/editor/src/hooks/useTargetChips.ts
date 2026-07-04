import { useMemo } from "react";
import type { NodeId, Scene } from "@/engine/contracts";
import { getNode } from "@/engine/sceneQueries";

/**
 * 2c selection chips (Moda §1.5/§1.6): the agent's edit targets are a pure
 * mirror of the canvas selection set. Selecting nodes (shift/Cmd+click for
 * several) chips them; de-selecting a node drops its chip. There is no
 * separate chip state — a chip IS a selected node, so removing a chip means
 * de-selecting that node. Labels come from the live scene (Moda's two-layer
 * "layer name" / node-id display); a deleted node is already gone from the
 * selection set, so no pruning is needed here.
 */

export interface TargetChip {
  id: NodeId;
  name: string;
}

export function useTargetChips(
  scene: Scene,
  selectedNodeIds: NodeId[]
): { chips: TargetChip[]; targetNodeIds: NodeId[] } {
  const chips = useMemo(
    // `||` (not `??`) so an empty-string name also falls back to the id.
    () => selectedNodeIds.map((id) => ({ id, name: getNode(scene, id)?.name || id })),
    [selectedNodeIds, scene]
  );
  return { chips, targetNodeIds: selectedNodeIds };
}
