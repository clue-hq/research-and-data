import type { TurnContextReference } from "@/features/projects/model/chat-turn";
import type { WebAnnotation } from "@/features/design-editor/adapter/annotations";
import type { Scene } from "@/features/design-editor/engine/scene/contracts";
import { addressObjectId } from "@/features/design-editor/engine/webBridge";
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

/** Which comment lane the open artifact has: a site's, a web page's, or none (an ad, or
 * nothing open). Comments (2026-10-29): the lane does NOT depend on a design leg — a page's
 * comment box offers Add and Send to chat whatever the chat has open, and the server takes the
 * comments to the page they were left on (opening, reopening or moving the leg to it). */
export function commentLane(artifactKind: string | null): "site" | "web" | null {
  return artifactKind === "site" || artifactKind === "web" ? artifactKind : null;
}

/** Slice 2 (R-A2): what a turn says when the annotations ARE the message —
 * "Send to chat" on an empty composer, or Send pressed with chips and no
 * prose. The notes themselves ride the context refs, so the message only has
 * to point at them. */
export const ANNOTATIONS_ONLY_MESSAGE = "See annotations.";

/** The composer's chip for one annotation: its number and a short, readable
 * stand-in for the note. Sorted by `n` so the bar reads in the order the
 * badges were placed, whatever order the reducer's list happens to hold. */
export interface AnnotationChip {
  n: number;
  label: string;
}

export interface AnnotationSnapshot {
  documentId: string;
  documentVersion: number | null;
  items: readonly WebAnnotation[];
}

/**
 * Slice 2 (R-A2): the annotations a web turn carries — one exact document ref
 * followed by one `design_node` ref per annotation, in badge order, each
 * carrying the marketer's own note.
 *
 * The note is prefixed with its number so the agent can join the ref it is
 * reading to the badge the user is looking at (and to any "annotation 2" the
 * prose mentions). The object id is the ADDRESS id — `{nodeId}#{path}` for an
 * element inside a clone's DOM, the bare node id for a node the document owns
 * — which is the only form that names a sub-element of a web fragment.
 */
export function annotationContextRefs(
  snapshot: AnnotationSnapshot | null,
): TurnContextReference[] {
  if (snapshot === null || snapshot.items.length === 0) return [];
  const ordered = [...snapshot.items].sort((a, b) => a.n - b.n);
  return [
    {
      objectId: snapshot.documentId,
      objectType: "design_document",
      version: snapshot.documentVersion,
    },
    ...ordered.map(
      (item): TurnContextReference => ({
        objectId: addressObjectId(item.address),
        objectType: "design_node",
        version: snapshot.documentVersion,
        note: `${item.n}. ${item.note}`,
      }),
    ),
  ];
}

/** The chip bar above the composer. A long note is elided rather than wrapped:
 * the chip is a reminder of what annotation 2 said, and the full text rides
 * the turn regardless. */
export function annotationChips(
  items: readonly WebAnnotation[],
): AnnotationChip[] {
  return [...items]
    .sort((a, b) => a.n - b.n)
    .map((item) => ({
      n: item.n,
      label:
        item.note.length > 28
          ? `${item.note.slice(0, 28).trimEnd()}…`
          : item.note,
    }));
}
