import assert from "node:assert/strict";
import test from "node:test";
import { createEditor, Node as SlateNode, Transforms } from "slate";
import { withHistory } from "slate-history";
import type { ProjectComposerEditor } from "./project-composer";
import {
  clearSubmittedComposerDraft,
  createComposerValue,
  getComposerMentionIds,
  getComposerPromptText,
  removeSelectedComposerMention,
} from "./project-composer-editor";

const openAi = {
  id: "openai",
  imagePath: "/logos/openai.svg",
  label: "OpenAI",
  secondaryLabel: "www.openai.com",
  type: "account" as const,
};

test("composer serializes display references separately from prompt text", () => {
  const value = createComposerValue("Draft this for the account", [openAi]);

  assert.deepEqual(getComposerMentionIds(value), ["openai"]);
  assert.equal(getComposerPromptText(value), " Draft this for the account");
});

test("Backspace removal deletes the selected reference without clearing the draft", () => {
  const editor = createEditor() as ProjectComposerEditor;
  editor.isInline = (element) => element.type === "mention";
  editor.isVoid = (element) => element.type === "mention";
  editor.children = createComposerValue("Draft this for the account", [openAi]);
  Transforms.select(editor, {
    anchor: { offset: 0, path: [0, 1, 0] },
    focus: { offset: 0, path: [0, 1, 0] },
  });

  assert.equal(removeSelectedComposerMention(editor), true);
  assert.equal(SlateNode.string(editor), " Draft this for the account");
  assert.deepEqual(getComposerMentionIds(editor.children), []);
});

test("submit clears the accepted Slate draft and the next message starts clean", () => {
  const editor = withHistory(createEditor()) as ProjectComposerEditor;
  editor.children = createComposerValue("First message", [openAi]);

  assert.equal(
    clearSubmittedComposerDraft(editor, {
      entityIds: ["openai"],
      prompt: " First message",
    }),
    true,
  );
  assert.equal(getComposerPromptText(editor.children), "");
  assert.deepEqual(getComposerMentionIds(editor.children), []);
  assert.deepEqual(editor.history, { redos: [], undos: [] });

  Transforms.insertText(editor, "Second message");
  assert.equal(getComposerPromptText(editor.children), "Second message");
  assert.equal(
    clearSubmittedComposerDraft(editor, {
      entityIds: ["openai"],
      prompt: " First message",
    }),
    false,
  );
  assert.equal(getComposerPromptText(editor.children), "Second message");
});
