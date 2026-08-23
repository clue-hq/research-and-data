import type { TurnContextReference } from "@/features/projects/model/chat-turn";
import type { Scene } from "@/features/design-editor/engine/scene/contracts";
import { nodeDisplayName } from "@/features/design-editor/engine/scene/sceneQueries";

export interface EditTargetChip {
  label: string;
  nodeId: string;
}

export interface EditTargetSnapshot {
  documentId: string;
  documentVersion: number | null;
  targetNodeIds: readonly string[];
}

/** Selection order is presentation and runtime order; missing nodes stay removable. */
export function editTargetChips(
  scene: Scene | null,
  selectedIds: readonly string[],
): EditTargetChip[] {
  return selectedIds.map((nodeId) => {
    const node = scene?.nodes[nodeId];
    return { label: node ? nodeDisplayName(node) : nodeId, nodeId };
  });
}

/** One exact document ref, followed by the ordered node snapshot from the click-submit. */
export function editTargetContextRefs(
  snapshot: EditTargetSnapshot | null,
): TurnContextReference[] {
  if (snapshot === null || snapshot.targetNodeIds.length === 0) return [];
  return [
    {
      objectId: snapshot.documentId,
      objectType: "design_document",
      version: snapshot.documentVersion,
    },
    ...snapshot.targetNodeIds.map(
      (nodeId): TurnContextReference => ({
        objectId: nodeId,
        objectType: "design_node",
        version: snapshot.documentVersion,
      }),
    ),
  ];
}
