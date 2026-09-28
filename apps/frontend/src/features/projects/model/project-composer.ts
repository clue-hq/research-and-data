import type { BaseEditor, Descendant } from "slate";
import type { HistoryEditor } from "slate-history";
import type { ReactEditor } from "slate-react";
import type { ProjectEntity } from "./project-workspace";

export interface ProjectComposerAttachment {
  /** Design-reference uploads only: the design asset store's record id. */
  assetId?: string;
  /** Chat uploads (Task 12): the four durable fields a submission ref needs. */
  artifactKey?: string;
  byteCount?: number;
  error?: string;
  filename: string;
  id: string;
  mediaType: string;
  sha256?: string;
  status: "failed" | "ready" | "uploading";
  type: "file";
  uploadId?: string;
  url: string;
}

export interface ProjectComposerMentionElement {
  accountName?: string;
  children: [{ text: "" }];
  entityId: string;
  entityType: ProjectEntity["type"];
  icon?: ProjectEntity["icon"];
  imagePath?: string;
  label: string;
  secondaryLabel: string;
  type: "mention";
  version?: number | null;
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
