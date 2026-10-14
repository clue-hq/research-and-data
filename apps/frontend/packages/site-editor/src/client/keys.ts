// Every history keystroke in the frame, decided once (review finding S2a-1).
//
// Puck registers its own undo/redo hotkeys on `document`, matches the PHYSICAL key (KeyZ / KeyY)
// and never checks whether the focus is in editable text; it then prevents the browser's own undo.
// The frame's keydown listener sits on `window` in the capture phase, so it runs before Puck's, and
// stopping the event there means Puck's history can never run. Undo is the server's stack
// (Contract 6 `shortcut`): outside text the frame asks the app for it; in editable text the browser's
// own text undo is left to work.

export interface FrameKeyAction {
  /** Stop the event before any other listener (Puck's history among them) sees it. */
  stop: boolean;
  /** Also cancel the browser's default action. */
  preventDefault: boolean;
  /** Ask the app for a server history step. */
  send: "undo" | "redo" | null;
}

const PASS: FrameKeyAction = { stop: false, preventDefault: false, send: null };

function editable(target: unknown): boolean {
  const element = target as { isContentEditable?: boolean; tagName?: string } | null;
  return Boolean(
    element &&
      (element.isContentEditable === true ||
        element.tagName === "INPUT" ||
        element.tagName === "TEXTAREA" ||
        element.tagName === "SELECT"),
  );
}

export function frameKeyAction(event: {
  key: string;
  code: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  target: unknown;
}): FrameKeyAction {
  if (!event.metaKey && !event.ctrlKey) return PASS;
  const character = event.key.toLowerCase();
  // Puck's own preview toggle belongs to the app's Edit button.
  if (character === "i") return { stop: true, preventDefault: true, send: null };
  const historyCharacter = character === "z" || character === "y";
  const historyKey = event.code === "KeyZ" || event.code === "KeyY";
  if (!historyCharacter && !historyKey) return PASS;
  // In editable text, or on a layout where this physical key types another character, nothing of
  // ours runs and the browser keeps its default; Puck simply never sees the key.
  if (editable(event.target) || !historyCharacter) return { stop: true, preventDefault: false, send: null };
  return { stop: true, preventDefault: true, send: character === "y" || event.shiftKey ? "redo" : "undo" };
}
