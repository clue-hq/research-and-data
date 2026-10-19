/**
 * The web and ad lanes' undo/redo keys, decided once (review finding S2b-6). The listener is on the
 * window, so a key acts on the open artifact only while that artifact is on screen: hidden behind
 * the Target accounts table, the Gallery or a plan document, or with the panel closed, ⌘Z used to
 * undo it on the server with nothing on screen saying so. Native text editing keeps its own undo.
 * (The site lane applies the same `onScreen` gate to its own key rule, `shortcutFor`.)
 */
export function artifactHistoryKey(
  event: { ctrlKey: boolean; key: string; metaKey: boolean; shiftKey: boolean; target: unknown },
  onScreen: boolean,
): "undo" | "redo" | null {
  if (!onScreen) return null;
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") return null;
  const target = event.target as { isContentEditable?: boolean; tagName?: string } | null;
  if (target && (target.isContentEditable === true || target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return null;
  return event.shiftKey ? "redo" : "undo";
}
