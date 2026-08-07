import {
  Editor,
  Element as SlateElement,
  Node as SlateNode,
  Transforms,
  type Descendant,
} from "slate";
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
    imagePath: entity.imagePath,
    label: entity.label,
    secondaryLabel: entity.secondaryLabel,
    type: "mention",
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
