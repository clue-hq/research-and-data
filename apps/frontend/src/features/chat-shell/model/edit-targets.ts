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

/** Selection order is presentation and runtime order. Only nodes the live
 * scene still carries become chips — the same filter the submission snapshot
 * applies — so what the bar shows is exactly what a send would target. A node
 * deleted out from under the selection (an agent turn, a manual edit) simply
 * drops off, rather than lingering as a chip labelled with a raw engine id
 * whose submission the server must refuse. */
export function editTargetChips(
  scene: Scene | null,
  selectedIds: readonly string[],
): EditTargetChip[] {
  if (!scene) return [];
  return selectedIds.flatMap((nodeId) => {
    const node = scene.nodes[nodeId];
    return node ? [{ label: nodeDisplayName(node), nodeId }] : [];
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
