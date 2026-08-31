export const ARTIFACT_ACTIONS = [
  "rename",
  "duplicate",
  "undo",
  "redo",
  "versions",
  "archive",
  "delete",
] as const;

export type ArtifactAction = (typeof ARTIFACT_ACTIONS)[number];

export type ArtifactActionRequest = Exclude<ArtifactAction, "rename">;
