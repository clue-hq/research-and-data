export type EditorPanelMode = "inspector" | "agent" | "export" | "diagnostics";
export type FutureEditorPanelMode = EditorPanelMode | "personalization";

export interface EditorPanelModeItem {
  mode: EditorPanelMode;
  label: string;
  ariaLabel?: string;
}

export const EDITOR_PANEL_MODES: EditorPanelModeItem[] = [
  { mode: "inspector", label: "Inspect" },
  { mode: "agent", label: "Agent" },
  { mode: "export", label: "Export", ariaLabel: "Export panel" },
  { mode: "diagnostics", label: "Diagnostics", ariaLabel: "Diagnostics panel" }
];

export function rightSidebarLabelForMode(mode: EditorPanelMode): string {
  switch (mode) {
    case "agent":
      return "Agent chat sidebar";
    case "export":
      return "Export sidebar";
    case "diagnostics":
      return "Diagnostics sidebar";
    case "inspector":
      return "Inspector sidebar";
  }
}
