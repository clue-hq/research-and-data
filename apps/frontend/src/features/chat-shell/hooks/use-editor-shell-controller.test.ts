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
    panelOpen: true,
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

test("opening target accounts switches surface, opens the rail, and leaves edit mode", () => {
  const state = editorShellReducer(
    stateWith({ editing: true, panelOpen: false, surface: "artifact" }),
    { type: "open-target-accounts" },
  );
  assert.equal(state.surface, "target-accounts");
  assert.equal(state.panelOpen, true);
  assert.equal(state.editing, false);
  // The open tabs survive the trip — the table is a surface, not a tab.
  assert.deepEqual(state.openArtifacts, artifacts);
  assert.equal(state.activeArtifactId, "b");
});

test("opening an artifact or the gallery leaves the target-accounts surface", () => {
  const fromTable = stateWith({ surface: "target-accounts" });
  assert.equal(
    editorShellReducer(fromTable, { type: "open-gallery" }).surface,
    "gallery",
  );
  assert.equal(
    editorShellReducer(fromTable, { artifactId: "c", type: "activate-artifact" })
      .surface,
    "artifact",
  );
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

test("re-opening the tab already in front is a no-op — edit mode and the selection survive", () => {
  // A feed refresh carrying the person's own write re-dispatches open-artifact
  // for the active tab. Until 2026-09-20 that reset editing and the inspector
  // selection on every change they made.
  const before = stateWith({
    activeArtifactId: "b",
    editing: true,
    inspectorSelection: "text",
  });
  const after = editorShellReducer(before, {
    artifact: { id: "b", kind: "web", title: "Pricing page" },
    type: "open-artifact",
  });
  assert.equal(after, before);

  // Opening the same artifact from the GALLERY (not in front) still brings it
  // forward with a fresh, non-editing canvas.
  const fromGallery = editorShellReducer(
    stateWith({ activeArtifactId: "b", editing: true, surface: "gallery" }),
    { artifact: { id: "b", kind: "web", title: "Pricing page" }, type: "open-artifact" },
  );
  assert.equal(fromGallery.surface, "artifact");
  assert.equal(fromGallery.editing, false);

  // And with the rail closed, opening the active artifact opens the rail.
  const fromClosed = editorShellReducer(
    stateWith({ activeArtifactId: "b", panelOpen: false }),
    { artifact: { id: "b", kind: "web", title: "Pricing page" }, type: "open-artifact" },
  );
  assert.equal(fromClosed.panelOpen, true);
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

// --- Phase C (C-3): the panel pair the chats route needs -------------------

test("panel state: initial defaults open; explicit panelOpen/surface respected", () => {
  const dflt = createInitialEditorShellState({});
  assert.equal(dflt.panelOpen, true);

  const closed = createInitialEditorShellState({ panelOpen: false });
  assert.equal(closed.panelOpen, false);

  const forcedArtifact = createInitialEditorShellState({
    panelOpen: true,
    surface: "artifact",
  });
  assert.equal(forcedArtifact.surface, "artifact");
  assert.equal(forcedArtifact.activeArtifactId, null);
});

test("toggle-panel from closed opens onto the gallery and leaves edit mode", () => {
  const state = editorShellReducer(
    stateWith({ editing: true, panelOpen: false, surface: "artifact" }),
    { type: "toggle-panel" },
  );
  assert.equal(state.panelOpen, true);
  assert.equal(state.surface, "gallery");
  assert.equal(state.editing, false);
});

test("toggle-panel from open closes the rail and resets edit + maximize", () => {
  const state = editorShellReducer(
    stateWith({ artifactMaximized: true, editing: true, panelOpen: true }),
    { type: "toggle-panel" },
  );
  assert.equal(state.panelOpen, false);
  assert.equal(state.editing, false);
  assert.equal(state.artifactMaximized, false);
});

test("opening an artifact, activating a tab, or opening the gallery reopens a closed panel", () => {
  const viaOpen = editorShellReducer(stateWith({ panelOpen: false }), {
    artifact: { id: "d", kind: "web", title: "New page" },
    type: "open-artifact",
  });
  assert.equal(viaOpen.panelOpen, true);

  const viaActivate = editorShellReducer(stateWith({ panelOpen: false }), {
    artifactId: "a",
    type: "activate-artifact",
  });
  assert.equal(viaActivate.panelOpen, true);

  const viaGallery = editorShellReducer(stateWith({ panelOpen: false }), {
    type: "open-gallery",
  });
  assert.equal(viaGallery.panelOpen, true);
});

test("Plan opens from an artifact without losing its tabs and can reopen after panel closure", () => {
  const plan = editorShellReducer(stateWith({ editing: true, panelOpen: false }), { type: "open-plan" });
  assert.equal(plan.surface, "plan");
  assert.equal(plan.editing, false);
  assert.equal(plan.panelOpen, true);
  assert.deepEqual(plan.openArtifacts, artifacts);
  const closed = editorShellReducer(plan, { type: "toggle-panel" });
  assert.equal(closed.panelOpen, false);
  assert.equal(editorShellReducer(closed, { type: "open-plan" }).surface, "plan");
  assert.equal(editorShellReducer(plan, { type: "open-gallery" }).surface, "gallery");
});
