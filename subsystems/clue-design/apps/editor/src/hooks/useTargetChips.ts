import { useEffect, useMemo, useState } from "react";
import type { NodeId, Scene } from "@/engine/contracts";
import { getNode } from "@/engine/sceneQueries";

/**
 * 2c selection chips (Moda §1.5/§1.6): the set of nodes the human has chipped
 * as edit targets for the agent. Selecting a node adds a chip; chips persist
 * across turns (the target set is deliberate, not the transient canvas
 * selection) and each is removable. The chip set becomes `target_node_ids` on
 * the turn. Chips for deleted nodes are pruned; labels stay fresh via the
 * live scene (Moda's two-layer "layer name" / node-id display).
 */

export interface TargetChip {
  id: NodeId;
  name: string;
}

export interface UseTargetChips {
  chips: TargetChip[];
  targetNodeIds: NodeId[];
  removeChip: (id: NodeId) => void;
  clearChips: () => void;
}

export function useTargetChips(scene: Scene, selectedNodeId: NodeId | null): UseTargetChips {
  const [chipIds, setChipIds] = useState<NodeId[]>([]);

  // Selecting a node adds it to the target set (deduped). Deselecting never
  // removes a chip — the set persists until the human removes it.
  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    setChipIds((current) =>
      current.includes(selectedNodeId) ? current : [...current, selectedNodeId]
    );
  }, [selectedNodeId]);

  // Drop chips whose node no longer exists (deleted / rejected turn). Only
  // replace the array when something actually changed, so unrelated edits
  // don't churn the chip identity.
  useEffect(() => {
    setChipIds((current) => {
      const next = current.filter((id) => Boolean(scene.nodes[id]));
      return next.length === current.length ? current : next;
    });
  }, [scene]);

  const chips = useMemo(
    () => chipIds.map((id) => ({ id, name: getNode(scene, id)?.name ?? id })),
    [chipIds, scene]
  );

  const removeChip = (id: NodeId) =>
    setChipIds((current) => current.filter((chipId) => chipId !== id));
  const clearChips = () => setChipIds([]);

  return { chips, targetNodeIds: chipIds, removeChip, clearChips };
}
