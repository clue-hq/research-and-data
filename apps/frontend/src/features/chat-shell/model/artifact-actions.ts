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

/** A real version list for the action menu's Versions submenu (sites, Wave 2 C9). Absent → the
 * menu keeps its existing list for the kinds that have no version read yet. */
export interface ArtifactVersionsBinding {
  loading: boolean;
  open: () => void;
  options: readonly { id: string; label: string }[];
  select: (id: string) => void;
  selectedId: string | null;
}
