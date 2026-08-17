import assert from "node:assert/strict";
import { test } from "node:test";
import type { ChatShellOpenArtifact } from "../model/chat-shell";
import {
  createInitialEditorShellState,
  editorShellReducer,
  type EditorShellState,
} from "./use-editor-shell-controller";

const artifacts: ChatShellOpenArtifact[] = [
  { id: "a", kind: "web", title: "Landing page" },
  { id: "b", kind: "web", title: "Pricing page" },
  { id: "c", kind: "ad", title: "Ad set" },
];

function stateWith(overrides: Partial<EditorShellState>): EditorShellState {
  return {
    activeArtifactId: "b",
    artifactMaximized: false,
    editing: false,
    inspectorSelection: "canvas",
    openArtifacts: artifacts,
    surface: "artifact",
    ...overrides,
  };
}

test("initial state has no default-tab fabrication and lands empty starts on gallery", () => {
  const empty = createInitialEditorShellState({});
  assert.deepEqual(empty.openArtifacts, []);
  assert.equal(empty.activeArtifactId, null);
  assert.equal(empty.surface, "gallery");

  const seeded = createInitialEditorShellState({ openArtifacts: artifacts });
  assert.deepEqual(seeded.openArtifacts, artifacts);
  assert.equal(seeded.activeArtifactId, "a");
  assert.equal(seeded.surface, "artifact");

  const pinned = createInitialEditorShellState({
    artifactId: "c",
    openArtifacts: artifacts,
  });
  assert.equal(pinned.activeArtifactId, "c");
});

test("activating a tab returns to the artifact surface and resets the selection", () => {
  const state = editorShellReducer(
    stateWith({ activeArtifactId: "a", inspectorSelection: "text", surface: "gallery" }),
    { artifactId: "c", type: "activate-artifact" },
  );
  assert.equal(state.activeArtifactId, "c");
  assert.equal(state.inspectorSelection, "canvas");
  assert.equal(state.surface, "artifact");
});

test("opening the gallery switches surface and leaves edit mode", () => {
  const state = editorShellReducer(stateWith({ editing: true }), {
    type: "open-gallery",
  });
  assert.equal(state.surface, "gallery");
  assert.equal(state.editing, false);
  assert.equal(state.activeArtifactId, "b");
});

test("opening an artifact appends once and activates it", () => {
  const next: ChatShellOpenArtifact = { id: "d", kind: "web", title: "New page" };
  const opened = editorShellReducer(
    stateWith({ editing: true, inspectorSelection: "image" }),
    { artifact: next, type: "open-artifact" },
  );
  assert.deepEqual(
    opened.openArtifacts.map((artifact) => artifact.id),
    ["a", "b", "c", "d"],
  );
  assert.equal(opened.activeArtifactId, "d");
  assert.equal(opened.editing, false);
  assert.equal(opened.inspectorSelection, "canvas");

  const reopened = editorShellReducer(opened, {
    artifact: { id: "a", kind: "web", title: "Landing page" },
    type: "open-artifact",
  });
  assert.deepEqual(
    reopened.openArtifacts.map((artifact) => artifact.id),
    ["a", "b", "c", "d"],
  );
  assert.equal(reopened.activeArtifactId, "a");
});

test("closing the active tab activates the next tab", () => {
  const state = editorShellReducer(stateWith({ activeArtifactId: "b" }), {
    artifactId: "b",
    type: "close-artifact",
  });
  assert.deepEqual(
    state.openArtifacts.map((artifact) => artifact.id),
    ["a", "c"],
  );
  assert.equal(state.activeArtifactId, "c");
});

test("closing the active last tab activates the previous tab", () => {
  const state = editorShellReducer(stateWith({ activeArtifactId: "c" }), {
    artifactId: "c",
    type: "close-artifact",
  });
  assert.equal(state.activeArtifactId, "b");
});

test("closing the only tab falls back to the gallery surface (founder Decision 1, 2026-08-17)", () => {
  const state = editorShellReducer(
    stateWith({
      activeArtifactId: "a",
      editing: true,
      openArtifacts: [artifacts[0]],
    }),
    { artifactId: "a", type: "close-artifact" },
  );
  assert.deepEqual(state.openArtifacts, []);
  assert.equal(state.activeArtifactId, null);
  assert.equal(state.editing, false);
  assert.equal(state.surface, "gallery");
});

test("closing the active tab with siblings stays on the artifact surface", () => {
  const state = editorShellReducer(stateWith({ activeArtifactId: "b" }), {
    artifactId: "b",
    type: "close-artifact",
  });
  assert.equal(state.surface, "artifact");
});

test("closing an inactive tab keeps the active tab", () => {
  const state = editorShellReducer(stateWith({ activeArtifactId: "c" }), {
    artifactId: "a",
    type: "close-artifact",
  });
  assert.deepEqual(
    state.openArtifacts.map((artifact) => artifact.id),
    ["b", "c"],
  );
  assert.equal(state.activeArtifactId, "c");
});

test("renaming trims the title and ignores empty input", () => {
  const renamed = editorShellReducer(stateWith({}), {
    artifactId: "a",
    title: "  Homepage  ",
    type: "rename-artifact",
  });
  assert.equal(renamed.openArtifacts[0]?.title, "Homepage");
  assert.equal(renamed.openArtifacts[1]?.title, "Pricing page");

  const ignored = editorShellReducer(stateWith({}), {
    artifactId: "a",
    title: "   ",
    type: "rename-artifact",
  });
  assert.equal(ignored.openArtifacts[0]?.title, "Landing page");
});

test("maximize toggles and restore always clears it", () => {
  const maximized = editorShellReducer(stateWith({}), { type: "toggle-maximized" });
  assert.equal(maximized.artifactMaximized, true);
  const restored = editorShellReducer(maximized, { type: "toggle-maximized" });
  assert.equal(restored.artifactMaximized, false);
  const escaped = editorShellReducer(maximized, { type: "restore-maximized" });
  assert.equal(escaped.artifactMaximized, false);
});

test("entering edit mode resets the inspector selection to canvas", () => {
  const editing = editorShellReducer(stateWith({ inspectorSelection: "button" }), {
    editing: true,
    type: "set-editing",
  });
  assert.equal(editing.editing, true);
  assert.equal(editing.inspectorSelection, "canvas");

  const selected = editorShellReducer(editing, {
    selection: "section",
    type: "select-inspector-element",
  });
  assert.equal(selected.inspectorSelection, "section");

  const done = editorShellReducer(selected, { editing: false, type: "set-editing" });
  assert.equal(done.editing, false);
  assert.equal(done.inspectorSelection, "section");
});
