import assert from "node:assert/strict";
import { test } from "node:test";
import { frameKeyAction } from "../src/client/keys";

// Review finding S2a-1: Puck registers its own undo/redo on `document`, matches the PHYSICAL key and
// never checks for editable text. One decision for every history keystroke, made in the frame's
// window-capture listener, keeps Puck's history from ever running.
const text = { isContentEditable: true, tagName: "H1" };
const body = { isContentEditable: false, tagName: "BODY" };
const input = { isContentEditable: false, tagName: "INPUT" };
const textarea = { isContentEditable: false, tagName: "TEXTAREA" };
const key = (over: Partial<Parameters<typeof frameKeyAction>[0]>) =>
  frameKeyAction({ key: "z", code: "KeyZ", metaKey: true, ctrlKey: false, shiftKey: false, target: body, ...over });

test("⌘Z outside text is the server's undo; ⇧⌘Z and ⌘Y are redo; Windows Ctrl works the same", () => {
  assert.deepEqual(key({}), { stop: true, preventDefault: true, send: "undo" });
  assert.deepEqual(key({ shiftKey: true }), { stop: true, preventDefault: true, send: "redo" });
  assert.deepEqual(key({ key: "y", code: "KeyY" }), { stop: true, preventDefault: true, send: "redo" });
  assert.deepEqual(key({ metaKey: false, ctrlKey: true }), { stop: true, preventDefault: true, send: "undo" });
  assert.deepEqual(key({ metaKey: false, ctrlKey: true, key: "y", code: "KeyY" }), { stop: true, preventDefault: true, send: "redo" });
  assert.deepEqual(key({ key: "Z", shiftKey: true }), { stop: true, preventDefault: true, send: "redo" });
});

test("in editable text the browser's own undo runs and Puck never sees the key", () => {
  for (const target of [text, input, textarea]) {
    assert.deepEqual(key({ target }), { stop: true, preventDefault: false, send: null });
    assert.deepEqual(key({ target, shiftKey: true }), { stop: true, preventDefault: false, send: null });
  }
});

test("QWERTZ: the z character on the KeyY key is undo, never Puck's redo", () => {
  assert.deepEqual(key({ code: "KeyY" }), { stop: true, preventDefault: true, send: "undo" });
  assert.deepEqual(key({ key: "y", code: "KeyZ" }), { stop: true, preventDefault: true, send: "redo" });
});

test("Dvorak: the KeyZ key typing ';' runs nothing and Puck never sees it", () => {
  assert.deepEqual(key({ key: ";" }), { stop: true, preventDefault: false, send: null });
  assert.deepEqual(key({ key: "t", code: "KeyY" }), { stop: true, preventDefault: false, send: null });
});

test("⌘I is swallowed (the Edit button owns preview); plain keys and other shortcuts pass", () => {
  assert.deepEqual(key({ key: "i", code: "KeyI" }), { stop: true, preventDefault: true, send: null });
  assert.deepEqual(key({ metaKey: false }), { stop: false, preventDefault: false, send: null });
  assert.deepEqual(key({ key: "c", code: "KeyC" }), { stop: false, preventDefault: false, send: null });
  assert.deepEqual(key({ target: null }), { stop: true, preventDefault: true, send: "undo" });
});

// Sync-fix review F6. Puck's preview toggle matches the PHYSICAL KeyI too, and Puck does not track
// the left Alt key, so every ⌘/Ctrl chord on the Z, Y or I keys is stopped before Puck sees it; ours
// acts only on the real character, without Alt.
const STOP_ONLY = { stop: true, preventDefault: false, send: null };

test("Dvorak ⌘C and Colemak ⌘U (the physical I key) still copy / underline, and Puck's preview toggle never sees them", () => {
  assert.deepEqual(key({ key: "c", code: "KeyI" }), STOP_ONLY);
  assert.deepEqual(key({ key: "c", code: "KeyI", metaKey: false, ctrlKey: true }), STOP_ONLY);
  assert.deepEqual(key({ key: "u", code: "KeyI" }), STOP_ONLY);
  assert.deepEqual(key({ key: "c", code: "KeyI", target: text }), STOP_ONLY);
  assert.deepEqual(key({ key: "i", code: "KeyG" }), { stop: true, preventDefault: true, send: null }, "⌘I by character stays swallowed");
});

test("an Alt chord on a history key is never a history step, and Puck never sees it", () => {
  assert.deepEqual(key({ metaKey: false, ctrlKey: true, altKey: true }), STOP_ONLY, "Ctrl+Alt+Z on Windows");
  assert.deepEqual(key({ key: "Ω", altKey: true }), STOP_ONLY, "⌥⌘Z on a Mac");
  assert.deepEqual(key({ key: "ż", metaKey: false, ctrlKey: true, altKey: true }), STOP_ONLY, "AltGr+Z typing ż (Polish)");
  assert.deepEqual(key({ key: "y", code: "KeyY", altKey: true, shiftKey: true }), STOP_ONLY);
  assert.deepEqual(key({ key: "i", code: "KeyI", altKey: true }), STOP_ONLY);
  assert.deepEqual(key({ key: "c", code: "KeyC", altKey: true }), { stop: false, preventDefault: false, send: null });
});

test("text inside a shadow root is editable text: the event's real target is read through its composed path", () => {
  const host = { isContentEditable: false, tagName: "AGENT-SECTION" };
  assert.deepEqual(key({ target: host, composedPath: () => [input, host, body] }), STOP_ONLY);
  assert.deepEqual(key({ target: host, composedPath: () => [text, host] }), STOP_ONLY);
  assert.deepEqual(key({ target: host, composedPath: () => [host, body] }), { stop: true, preventDefault: true, send: "undo" });
  assert.deepEqual(key({ target: host, composedPath: () => [] }), { stop: true, preventDefault: true, send: "undo" });
});
