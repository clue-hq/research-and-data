/** Keyboard-shortcut interpretation for the editor shell. Pure functions —
 * the shell decides what a key means; the caller decides whether it's allowed. */

export function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return (
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select" ||
    target.isContentEditable
  );
}

export function keyboardHistoryAction(event: KeyboardEvent): "undo" | "redo" | null {
  const key = event.key.toLowerCase();
  const modifier = event.metaKey || event.ctrlKey;
  if (!modifier) {
    return null;
  }
  if (key === "z" && event.shiftKey) {
    return "redo";
  }
  if (key === "z") {
    return "undo";
  }
  if (key === "y") {
    return "redo";
  }
  return null;
}

export type ArrangeAction =
  | "group"
  | "ungroup"
  | "to_front"
  | "to_back"
  | "forward"
  | "backward";

/** Phase 4b arrange shortcuts: ⌘G group, ⌘⇧G ungroup, ⌘] forward, ⌘[
 * backward, ⌥⌘] to front, ⌥⌘[ to back. Mirrors `keyboardHistoryAction`'s
 * shape — pure interpretation, the caller decides whether it's allowed. */
export function keyboardArrangeAction(event: KeyboardEvent): ArrangeAction | null {
  const modifier = event.metaKey || event.ctrlKey;
  if (!modifier) {
    return null;
  }
  const key = event.key.toLowerCase();
  if (key === "g") {
    return event.shiftKey ? "ungroup" : "group";
  }
  if (key === "]") {
    return event.altKey ? "to_front" : "forward";
  }
  if (key === "[") {
    return event.altKey ? "to_back" : "backward";
  }
  return null;
}

export function arrowNudge(key: string): { x: number; y: number } | null {
  switch (key) {
    case "ArrowLeft":
      return { x: -1, y: 0 };
    case "ArrowRight":
      return { x: 1, y: 0 };
    case "ArrowUp":
      return { x: 0, y: -1 };
    case "ArrowDown":
      return { x: 0, y: 1 };
    default:
      return null;
  }
}
