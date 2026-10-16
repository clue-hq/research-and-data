import type { NodeId, Operation, PageId, Scene } from "../engine/scene/contracts";
import { removeNode } from "../engine/scene/operations";
import { nodeDisplayName } from "../engine/scene/sceneQueries";
import { isTypingTarget } from "./scene-arrange";
import { rootFrameId } from "./scene-hydrate";

/**
 * The Delete key over the scene canvas: the selected elements go, together with
 * everything nested inside them, in ONE batch (one optimistic apply, one undo
 * frame).
 *
 * Founder ruling 2026-10-16:
 *  • a container goes WITH its contents. Keeping the children would mean lifting
 *    them out of an auto-layout box into its parent, which re-flows the layout and
 *    moves them — a worse surprise than the delete;
 *  • because most containers read as an empty transparent box, a delete that took
 *    nested elements with it says so in the inspector's note line, with the undo
 *    chord. A plain image or text box says nothing;
 *  • the page's artboard (its root frame) is never deleted by the key.
 *
 * Pure so the rules are testable without React; `use-scene-delete.ts` only binds
 * the key and dispatches.
 */

export type SceneDeletePlan =
  /** Nothing to delete — a non-event, so the key is left to the browser. */
  | { kind: "none" }
  /** The selection cannot be deleted; `note` says why. Nothing is written. */
  | { kind: "refuse"; note: string }
  | { kind: "delete"; operations: Operation[]; note: string | null };

/**
 * Is this keydown the Delete key? Mac's "delete" key is `Backspace`; the forward
 * delete key (Windows/Linux Delete, Mac fn+delete) is `Delete`. Any modifier
 * makes it someone else's chord (⌘⌫ / Ctrl+Backspace edit text, Shift+Delete is
 * cut on Windows), and a focused field keeps its own Backspace.
 */
export function deleteShortcut(
  event: {
    altKey: boolean;
    ctrlKey: boolean;
    key: string;
    metaKey: boolean;
    repeat: boolean;
    shiftKey: boolean;
  },
  target: {
    isContentEditable: boolean;
    tagName: string;
    closest?: (selector: string) => unknown;
  } | null,
): boolean {
  if (event.key !== "Backspace" && event.key !== "Delete") return false;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
  // Holding the key must not chew through the tree one level at a time.
  if (event.repeat) return false;
  if (isTypingTarget(target) || target?.tagName === "SELECT") return false;
  // A key pressed inside an open panel, menu or dropdown (the asset library, the Replace-image
  // menu) belongs to it: a focused library tile must not delete the image it would replace.
  if (target?.closest?.(OVERLAY_SELECTOR)) return false;
  return true;
}

const OVERLAY_SELECTOR = '[role="dialog"], [role="menu"], [role="listbox"]';

function descendantIds(scene: Scene, nodeId: NodeId): NodeId[] {
  const found: NodeId[] = [];
  const stack = [...(scene.nodes[nodeId]?.children ?? [])];
  while (stack.length > 0) {
    const id = stack.pop()!;
    const node = scene.nodes[id];
    if (!node) continue;
    found.push(id);
    stack.push(...node.children);
  }
  return found;
}

function quotedName(scene: Scene, nodeId: NodeId): string {
  const node = scene.nodes[nodeId]!;
  return `"${node.name?.trim() || nodeDisplayName(node)}"`;
}

function elements(count: number): string {
  return count === 1 ? "1 element" : `${count} elements`;
}

/**
 * What pressing Delete does to this selection. `undoKeys` is the platform's undo
 * chord as the note should print it ("⌘Z" / "Ctrl+Z").
 */
export function planSceneDelete(
  scene: Scene | null,
  pageId: PageId | null,
  selectedIds: readonly NodeId[],
  undoKeys: string,
): SceneDeletePlan {
  if (!scene) return { kind: "none" };
  const artboard = pageId ? rootFrameId(scene, pageId) : null;
  const present = [...new Set(selectedIds)].filter(
    (id) => scene.nodes[id] && id !== artboard,
  );
  // A node nested under another selected node already goes with it; removing it
  // separately would make the second remove name a node that no longer exists.
  const nested = new Set(present.flatMap((id) => descendantIds(scene, id)));
  const roots = present.filter((id) => !nested.has(id));
  if (roots.length === 0) return { kind: "none" };

  // The engine's safe delete refuses a locked node or a locked descendant; the
  // key keeps that rule, and refuses the whole selection rather than half of it.
  for (const id of roots) {
    const lockedId = [id, ...descendantIds(scene, id)].find(
      (candidate) => scene.nodes[candidate]?.locked,
    );
    if (lockedId) {
      return {
        kind: "refuse",
        note:
          lockedId === id
            ? `${quotedName(scene, id)} is locked, so it can't be deleted.`
            : `${quotedName(scene, id)} has a locked element inside it (${quotedName(scene, lockedId)}), so it can't be deleted.`,
      };
    }
  }

  const inside = roots.reduce((sum, id) => sum + descendantIds(scene, id).length, 0);
  let note: string | null = null;
  if (inside > 0) {
    note =
      roots.length === 1
        ? `Deleted ${quotedName(scene, roots[0])} and ${elements(inside)} inside it. ${undoKeys} to undo.`
        : `Deleted ${elements(roots.length)} and ${elements(inside)} inside them. ${undoKeys} to undo.`;
  }
  return { kind: "delete", operations: roots.map(removeNode), note };
}
