// Every history keystroke in the frame, decided once (review findings S2a-1, sync-fix F6).
//
// Puck registers its own undo/redo and preview-toggle hotkeys on `document`, matches the PHYSICAL
// key (KeyZ / KeyY / KeyI) with ⌘ or Ctrl, does not track the left Alt key, and never checks whether
// the focus is in editable text; it then prevents the browser's own default.
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
  /** Let the key reach the rich text editor it was typed in (TipTap: its own undo, redo and italic),
   * then stop it on its way up, before Puck's listener on `document` (editor-app's body listener). */
  shield: boolean;
}

const PASS: FrameKeyAction = { stop: false, preventDefault: false, send: null, shield: false };

/** Puck's modifier hotkeys, by physical key. */
const PUCK_KEYS = new Set(["KeyZ", "KeyY", "KeyI"]);

/** A rich text field (plan 2): TipTap's editor, which handles its own history and marks. */
function inRichText(target: unknown): boolean {
  const element = target as { closest?: (selector: string) => unknown } | null;
  return Boolean(element && typeof element.closest === "function" && element.closest(".ProseMirror"));
}

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
  altKey?: boolean;
  target: unknown;
  /** The real target: at `window`, `target` is retargeted to the host of an (open) shadow root. */
  composedPath?: () => unknown[];
}): FrameKeyAction {
  if (!event.metaKey && !event.ctrlKey) return PASS;
  const character = event.key.toLowerCase();
  const ours = character === "z" || character === "y" || character === "i";
  if (!ours && !PUCK_KEYS.has(event.code)) return PASS;
  // From here Puck never sees the key. With Alt (⌥⌘Z, Ctrl+Alt+Z, AltGr), or on a layout where this
  // physical key types another character (Dvorak's ⌘C on the I key), nothing of ours runs either and
  // the browser keeps its default.
  if (event.altKey || !ours) return { stop: true, preventDefault: false, send: null, shield: false };
  const target = event.composedPath?.()[0] ?? event.target;
  // In rich text the editor's own undo, redo and italic run; Puck still never sees the key.
  if (inRichText(target)) return { stop: false, preventDefault: false, send: null, shield: true };
  // In other editable text the browser's own text undo and italic run. Outside text, Puck's preview
  // toggle (⌘I) belongs to the app's Edit button.
  if (editable(target)) return { stop: true, preventDefault: false, send: null, shield: false };
  if (character === "i") return { stop: true, preventDefault: true, send: null, shield: false };
  return { stop: true, preventDefault: true, send: character === "y" || event.shiftKey ? "redo" : "undo", shield: false };
}
