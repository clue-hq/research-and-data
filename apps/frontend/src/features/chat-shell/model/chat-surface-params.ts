import {
  parseChatShellInspectorSelection,
  type ChatShellInspectorSelection,
} from "./chat-shell";

// The ?surface=/edit=/selection= pane-state vocabulary (founder ruling R2,
// 2026-08-17) mapped onto the editor-shell controller's initial state. URL
// state is read once at mount; pane toggles do not write back to the URL in
// Phase C (known deferral — the dummy build behaves the same way).

export interface ChatSurfaceUrlState {
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  panelOpen: boolean;
  surface: "artifact" | "gallery" | undefined;
}

export function chatSurfaceUrlState(query: {
  edit?: string;
  selection?: string;
  surface?: string;
}): ChatSurfaceUrlState {
  const surface =
    query.surface === "gallery"
      ? ("gallery" as const)
      : query.surface === "web" || query.surface === "ad"
        ? ("artifact" as const)
        : undefined;
  return {
    editing: surface === "artifact" && query.edit === "1",
    inspectorSelection: parseChatShellInspectorSelection(query.selection),
    panelOpen: surface !== undefined,
    surface,
  };
}
