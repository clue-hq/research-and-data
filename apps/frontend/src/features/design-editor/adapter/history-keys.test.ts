import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactHistoryKey } from "./history-keys";

// Review finding S2b-6: ⌘Z anywhere on the chat page undid the open artifact on the server — even
// with the artifact hidden behind the Target accounts table, the Gallery or a plan document, or with
// the panel closed. The web and ad lanes share this decision; the site lane applies the same gate.
const body = { isContentEditable: false, tagName: "BODY" };
const key = (over: Partial<Parameters<typeof artifactHistoryKey>[0]> = {}, onScreen = true) =>
  artifactHistoryKey({ ctrlKey: false, key: "z", metaKey: true, shiftKey: false, target: body, ...over }, onScreen);

test("⌘Z / ⇧⌘Z / Ctrl+Z are undo and redo while the artifact is on screen", () => {
  assert.equal(key(), "undo");
  assert.equal(key({ shiftKey: true }), "redo");
  assert.equal(key({ metaKey: false, ctrlKey: true }), "undo");
  assert.equal(key({ key: "Z", shiftKey: true }), "redo");
});

test("nothing happens while the artifact is not on screen", () => {
  assert.equal(key({}, false), null);
  assert.equal(key({ shiftKey: true }, false), null);
});

test("typing keeps its own undo, and other keys are not history", () => {
  for (const target of [{ isContentEditable: true, tagName: "DIV" }, { isContentEditable: false, tagName: "INPUT" }, { isContentEditable: false, tagName: "TEXTAREA" }]) {
    assert.equal(key({ target }), null);
  }
  assert.equal(key({ metaKey: false }), null);
  assert.equal(key({ key: "c" }), null);
  assert.equal(key({ target: null }), "undo");
});
