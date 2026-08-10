import assert from "node:assert/strict";
import test from "node:test";
import { createEditor, Node as SlateNode, Transforms } from "slate";
import type { ProjectComposerEditor } from "./project-composer";
import {
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
