import assert from "node:assert/strict";
import test from "node:test";
import {
  createInitialChatSessionMenuState,
  transitionChatSessionMenu,
} from "./use-chat-session-menu-controller";

const TITLE = "Launch review";

test("initial state starts closed, not renaming, with the title as draft", () => {
  const state = createInitialChatSessionMenuState(TITLE);
  assert.deepEqual(state, {
    draftTitle: TITLE,
    menuOpen: false,
    renameCancelled: false,
    renaming: false,
    statusMessage: "",
  });
});

test("toggle-menu opens and a second toggle closes", () => {
  const initial = createInitialChatSessionMenuState(TITLE);
  const opened = transitionChatSessionMenu(initial, { type: "toggle-menu" }, TITLE);
  assert.equal(opened.effect, null);
  assert.equal(opened.state.menuOpen, true);

  const closed = transitionChatSessionMenu(opened.state, { type: "toggle-menu" }, TITLE);
  assert.equal(closed.state.menuOpen, false);
});

test("dismiss (Escape / outside pointer) closes an open menu", () => {
  const open = {
    ...createInitialChatSessionMenuState(TITLE),
    menuOpen: true,
  };
  const { effect, state } = transitionChatSessionMenu(open, { type: "dismiss" }, TITLE);
  assert.equal(effect, null);
  assert.equal(state.menuOpen, false);
});

test("dismiss with the menu already closed is a state no-op", () => {
  const initial = createInitialChatSessionMenuState(TITLE);
  const { state } = transitionChatSessionMenu(initial, { type: "dismiss" }, TITLE);
  assert.equal(state, initial);
});

test("start-rename seeds the draft from the current title, closes the menu, enters renaming", () => {
  const open = {
    ...createInitialChatSessionMenuState("stale draft"),
    draftTitle: "stale draft",
    menuOpen: true,
    renameCancelled: true,
  };
  const { effect, state } = transitionChatSessionMenu(open, { type: "start-rename" }, TITLE);
  assert.equal(effect, null);
  assert.equal(state.draftTitle, TITLE);
  assert.equal(state.menuOpen, false);
  assert.equal(state.renameCancelled, false);
  assert.equal(state.renaming, true);
});

test("set-draft updates the draft title", () => {
  const renaming = { ...createInitialChatSessionMenuState(TITLE), renaming: true };
  const { state } = transitionChatSessionMenu(
    renaming,
    { draft: "New name", type: "set-draft" },
    TITLE,
  );
  assert.equal(state.draftTitle, "New name");
});

test("commit-rename with a non-empty draft emits a rename effect with the trimmed title", () => {
  const renaming = {
    ...createInitialChatSessionMenuState(TITLE),
    draftTitle: "  Renamed session  ",
    renaming: true,
  };
  const { effect, state } = transitionChatSessionMenu(renaming, { type: "commit-rename" }, TITLE);
  assert.deepEqual(effect, { kind: "rename", title: "Renamed session" });
  assert.equal(state.renaming, false);
});

test("commit-rename with a whitespace-only draft reverts the draft and emits nothing", () => {
  const renaming = {
    ...createInitialChatSessionMenuState(TITLE),
    draftTitle: "   ",
    renaming: true,
  };
  const { effect, state } = transitionChatSessionMenu(renaming, { type: "commit-rename" }, TITLE);
  assert.equal(effect, null);
  assert.equal(state.draftTitle, TITLE);
  assert.equal(state.renaming, false);
});

test("Escape-cancel followed by the input's blur commit does not rename", () => {
  const renaming = {
    ...createInitialChatSessionMenuState(TITLE),
    draftTitle: "half-typed",
    renaming: true,
  };
  const cancelled = transitionChatSessionMenu(renaming, { type: "cancel-rename" }, TITLE);
  assert.equal(cancelled.effect, null);
  assert.equal(cancelled.state.draftTitle, TITLE);
  assert.equal(cancelled.state.renameCancelled, true);
  assert.equal(cancelled.state.renaming, false);

  const blurred = transitionChatSessionMenu(cancelled.state, { type: "commit-rename" }, TITLE);
  assert.equal(blurred.effect, null);
  assert.equal(blurred.state.renameCancelled, false);
});

test("commit-rename while not renaming emits nothing (double-commit guard)", () => {
  const idle = { ...createInitialChatSessionMenuState(TITLE), draftTitle: "Renamed" };
  const { effect, state } = transitionChatSessionMenu(idle, { type: "commit-rename" }, TITLE);
  assert.equal(effect, null);
  assert.equal(state, idle);
});

test("archive emits the archive effect, announces it, and closes the menu", () => {
  const open = { ...createInitialChatSessionMenuState(TITLE), menuOpen: true };
  const { effect, state } = transitionChatSessionMenu(
    open,
    { action: "archive", type: "session-action" },
    TITLE,
  );
  assert.deepEqual(effect, { kind: "archive" });
  assert.equal(state.menuOpen, false);
  assert.equal(state.statusMessage, "Archive requested");
});

test("delete emits no effect and no status message (R5: rendered but inert)", () => {
  const open = { ...createInitialChatSessionMenuState(TITLE), menuOpen: true };
  const { effect, state } = transitionChatSessionMenu(
    open,
    { action: "delete", type: "session-action" },
    TITLE,
  );
  assert.equal(effect, null);
  assert.equal(state.menuOpen, false);
  assert.equal(state.statusMessage, "");
});

test("copy-status records the announcement and closes the menu", () => {
  const open = { ...createInitialChatSessionMenuState(TITLE), menuOpen: true };
  const { effect, state } = transitionChatSessionMenu(
    open,
    { message: "Session ID copied", type: "copy-status" },
    TITLE,
  );
  assert.equal(effect, null);
  assert.equal(state.menuOpen, false);
  assert.equal(state.statusMessage, "Session ID copied");
});
