import assert from "node:assert/strict";
import { test } from "node:test";
import { chatSurfaceUrlState } from "./chat-surface-params";

test("no surface param leaves the panel closed on the conversation", () => {
  assert.deepEqual(chatSurfaceUrlState({}), {
    editing: false,
    inspectorSelection: "canvas",
    panelOpen: false,
    surface: undefined,
  });
});

test("surface=gallery opens the rail on the gallery", () => {
  const state = chatSurfaceUrlState({ surface: "gallery" });
  assert.equal(state.panelOpen, true);
  assert.equal(state.surface, "gallery");
  assert.equal(state.editing, false);
});

test("surface=web|ad opens the artifact surface; edit=1 enters editing", () => {
  const web = chatSurfaceUrlState({ edit: "1", surface: "web" });
  assert.equal(web.panelOpen, true);
  assert.equal(web.surface, "artifact");
  assert.equal(web.editing, true);

  const ad = chatSurfaceUrlState({ surface: "ad" });
  assert.equal(ad.surface, "artifact");
  assert.equal(ad.editing, false);
});

test("selection parses through the inspector vocabulary with canvas fallback", () => {
  assert.equal(
    chatSurfaceUrlState({ selection: "text", surface: "web" }).inspectorSelection,
    "text",
  );
  assert.equal(
    chatSurfaceUrlState({ selection: "bogus", surface: "web" }).inspectorSelection,
    "canvas",
  );
});

test("edit with an unknown or absent surface never opens the rail or enters editing", () => {
  const unknown = chatSurfaceUrlState({ edit: "1", surface: "chat" });
  assert.equal(unknown.panelOpen, false);
  assert.equal(unknown.editing, false);

  const absent = chatSurfaceUrlState({ edit: "1" });
  assert.equal(absent.panelOpen, false);
  assert.equal(absent.editing, false);
});
