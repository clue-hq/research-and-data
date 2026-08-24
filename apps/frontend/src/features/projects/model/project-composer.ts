import type { BaseEditor, Descendant } from "slate";
import type { HistoryEditor } from "slate-history";
import type { ReactEditor } from "slate-react";

export interface ProjectComposerAttachment {
  assetId?: string;
  error?: string;
  filename: string;
  id: string;
  mediaType: string;
  status: "failed" | "ready" | "uploading";
  type: "file";
  url: string;
}

export interface ProjectComposerMentionElement {
  accountName?: string;
  children: [{ text: "" }];
  entityId: string;
  entityType: "account" | "contact";
  imagePath: string;
  label: string;
  secondaryLabel: string;
  type: "mention";
}

export interface ProjectComposerParagraphElement {
  children: Array<ProjectComposerMentionElement | ProjectComposerText>;
  type: "paragraph";
}

export interface ProjectComposerText {
  text: string;
}

export type ProjectComposerElement =
  | ProjectComposerMentionElement
  | ProjectComposerParagraphElement;

export type ProjectComposerEditor = BaseEditor & ReactEditor & HistoryEditor;

export type ProjectComposerValue = Descendant[];

declare module "slate" {
  interface CustomTypes {
    Editor: ProjectComposerEditor;
    Element: ProjectComposerElement;
    Text: ProjectComposerText;
  }
}
