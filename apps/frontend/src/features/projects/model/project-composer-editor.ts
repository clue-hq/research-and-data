import {
  Editor,
  Element as SlateElement,
  Node as SlateNode,
  Transforms,
  type Descendant,
} from "slate";
import { HistoryEditor } from "slate-history";
import type { ProjectEntity } from "./project-workspace";
import type {
  ProjectComposerEditor,
  ProjectComposerMentionElement,
  ProjectComposerParagraphElement,
} from "./project-composer";

export function createComposerMention(
  entity: ProjectEntity,
): ProjectComposerMentionElement {
  return {
    accountName: entity.accountName,
    children: [{ text: "" }],
    entityId: entity.id,
    entityType: entity.type,
    icon: entity.icon,
    imagePath: entity.imagePath,
    label: entity.label,
    secondaryLabel: entity.secondaryLabel,
    type: "mention",
    version: entity.version,
  };
}

export function createComposerValue(
  prompt: string,
  entities: ProjectEntity[],
): Descendant[] {
  const children: ProjectComposerParagraphElement["children"] = [{ text: "" }];

  entities.forEach((entity) => {
    children.push(createComposerMention(entity), { text: " " });
  });
  children.push({ text: prompt });

  return [{ children, type: "paragraph" }];
}

export function getComposerMentionIds(value: Descendant[]) {
  const ids: string[] = [];
  value.forEach((node) => {
    if (!SlateElement.isElement(node)) return;
    node.children.forEach((child) => {
      if (SlateElement.isElement(child) && child.type === "mention") {
        ids.push(child.entityId);
      }
    });
  });
  return ids;
}

export function getComposerPromptText(value: Descendant[]) {
  return value.map((node) => SlateNode.string(node)).join("\n");
}

export function removeSelectedComposerMention(editor: ProjectComposerEditor) {
  if (!editor.selection) return false;

  const selectedMention = Editor.above(editor, {
    at: editor.selection,
    match: (node) =>
      SlateElement.isElement(node) && node.type === "mention",
  });
  if (!selectedMention) return false;

  Transforms.removeNodes(editor, { at: selectedMention[1] });
  return true;
}

export interface SubmittedComposerDraft {
  entityIds: readonly string[];
  prompt: string;
}

function sameEntityIds(
  current: readonly string[],
  submitted: readonly string[],
): boolean {
  return (
    current.length === submitted.length &&
    current.every((entityId, index) => entityId === submitted[index])
  );
}

/**
 * Clear only the exact draft the server accepted.
 *
 * A user may start typing the next message while the submission request is in
 * flight. Comparing the current Slate value with the submitted snapshot keeps
 * that newer text intact. The reset is excluded from undo history so Cmd+Z
 * cannot resurrect a message that was already sent.
 */
export function clearSubmittedComposerDraft(
  editor: ProjectComposerEditor,
  submitted: SubmittedComposerDraft,
): boolean {
  const currentPrompt = getComposerPromptText(editor.children);
  const currentEntityIds = getComposerMentionIds(editor.children);
  if (
    currentPrompt !== submitted.prompt ||
    !sameEntityIds(currentEntityIds, submitted.entityIds)
  ) {
    return false;
  }

  HistoryEditor.withoutSaving(editor, () => {
    Editor.withoutNormalizing(editor, () => {
      Transforms.deselect(editor);
      for (let index = editor.children.length - 1; index >= 0; index -= 1) {
        Transforms.removeNodes(editor, { at: [index] });
      }
      Transforms.insertNodes(
        editor,
        { children: [{ text: "" }], type: "paragraph" },
        { at: [0] },
      );
      Transforms.select(editor, { offset: 0, path: [0, 0] });
    });
  });
  editor.history = { redos: [], undos: [] };
  return true;
}
