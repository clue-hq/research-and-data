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
