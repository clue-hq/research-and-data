import type { DesignDocumentKind } from "@/features/design-editor/model/artifact";

export type ChatShellArtifactKind = DesignDocumentKind;

export interface ChatShellOpenArtifact {
  id: string;
  kind: ChatShellArtifactKind;
  title: string;
}

export type ChatShellSurface =
  | "artifact"
  | "chat"
  | "gallery"
  | "target-accounts"
  | "plan";

export const CHAT_SHELL_INSPECTOR_SELECTIONS = [
  "canvas",
  "text",
  "image",
  "button",
  "auto-layout",
  "rectangle",
  "ellipse",
  "group",
  "icon",
  "container",
  "section",
] as const;

export type ChatShellInspectorSelection =
  (typeof CHAT_SHELL_INSPECTOR_SELECTIONS)[number];

export function parseChatShellInspectorSelection(
  value: string | undefined,
): ChatShellInspectorSelection {
  return CHAT_SHELL_INSPECTOR_SELECTIONS.includes(
    value as ChatShellInspectorSelection,
  )
    ? (value as ChatShellInspectorSelection)
    : "canvas";
}

export interface ChatShellInitialState {
  artifactId?: string;
  artifactKind?: ChatShellArtifactKind;
  artifactTitle?: string;
  chatId?: string;
  chatTitle?: string;
  editing?: boolean;
  inspectorReview?: boolean;
  inspectorSelection?: ChatShellInspectorSelection;
  openArtifacts?: ChatShellOpenArtifact[];
  projectId?: string;
  surface?: ChatShellSurface;
}
