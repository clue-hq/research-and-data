import assert from "node:assert/strict";
import { test } from "node:test";
import {
  chatDockContent,
  chatDockOpen,
  chatDockDismissedBySubmission,
  type ChatDockState,
} from "./chat-dock";

const editingWeb: ChatDockState = {
  artifactKind: "web",
  editing: true,
  panelOpen: true,
  surface: "artifact",
};

test("Edit-only entry: an open web artifact docks nothing until editing", () => {
  assert.equal(chatDockOpen({ ...editingWeb, editing: false }), false);
  assert.equal(
    chatDockContent({ ...editingWeb, editing: false }),
    "conversation",
  );
  assert.equal(chatDockOpen(editingWeb), true);
});

test("no dock without an open artifact (kind null)", () => {
  const noArtifact = { ...editingWeb, artifactKind: null };
  assert.equal(chatDockOpen(noArtifact), false);
  assert.equal(chatDockContent(noArtifact), "conversation");
});

test("the dock needs the artifact surface with the panel open", () => {
  assert.equal(chatDockOpen({ ...editingWeb, surface: "gallery" }), false);
  assert.equal(chatDockOpen({ ...editingWeb, panelOpen: false }), false);
  assert.equal(
    chatDockContent({ ...editingWeb, surface: "gallery" }),
    "conversation",
  );
});

test("the target-accounts surface docks nothing — it behaves like the gallery", () => {
  const targetAccounts: ChatDockState = { ...editingWeb, surface: "target-accounts" };
  assert.equal(chatDockOpen(targetAccounts), false);
  assert.equal(chatDockContent(targetAccounts), "conversation");
});

test("the docked inspector branches on the artifact kind", () => {
  assert.equal(chatDockContent(editingWeb), "web-inspector");
  assert.equal(
    chatDockContent({ ...editingWeb, artifactKind: "ad" }),
    "ad-inspector",
  );
});

test("only an accepted submission dismisses the dock", () => {
  assert.equal(chatDockDismissedBySubmission("accepted"), true);
  assert.equal(chatDockDismissedBySubmission("failed"), false);
  assert.equal(chatDockDismissedBySubmission("not_submitted"), false);
});
