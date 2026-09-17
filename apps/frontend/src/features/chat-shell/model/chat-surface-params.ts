import {
  parseChatShellInspectorSelection,
  type ChatShellArtifactKind,
  type ChatShellInspectorSelection,
} from "./chat-shell";

// The ?surface=/edit=/selection= pane-state vocabulary (founder ruling R2,
// 2026-08-17) as one round-trip pair: `chatSurfaceUrlState` hydrates the
// editor-shell controller's initial state from the URL (read once at mount),
// and `chatSurfacePaneParams` serializes the live pane state back out so any
// state the user reaches is a shareable deep link (chat-flow slice 5 — this
// closes the Phase-C write-back deferral). Hydration stays one-directional:
// the URL is written after mount, never re-read into state.
//
// The superseded `?artifact=` param is not part of this vocabulary and is
// never emitted.

export interface ChatSurfaceUrlState {
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  panelOpen: boolean;
  surface: "artifact" | "gallery" | "target-accounts" | "plan" | undefined;
}

function parseChatSurface(
  raw: string | undefined,
): "artifact" | "gallery" | "target-accounts" | "plan" | undefined {
  if (raw === "plan") return "plan";
  if (raw === "gallery") return "gallery";
  // The target-accounts rail surface is addressable by its own name — the
  // shareable route is /projects/:id/chats/:chatId?surface=target-accounts.
  if (raw === "target-accounts") return "target-accounts";
  if (raw === "web" || raw === "ad") return "artifact";
  // `chat` is the ratified alias of the conversation-only resting state (rail
  // closed, nothing editing) — deliberately the SAME state an absent param
  // lands on, spelled out here so the alias is a decision and not a
  // fall-through. It is accepted inbound; the write-back canonicalizes it
  // back to the bare URL (the resting state carries no pane params).
  if (raw === "chat") return undefined;
  return undefined;
}

export function chatSurfaceUrlState(query: {
  edit?: string;
  selection?: string;
  surface?: string;
}): ChatSurfaceUrlState {
  const surface = parseChatSurface(query.surface);
  return {
    editing: surface === "artifact" && query.edit === "1",
    inspectorSelection: parseChatShellInspectorSelection(query.selection),
    panelOpen: surface !== undefined,
    surface,
  };
}

/** The live pane state the chats route serializes back into the URL. */
export interface ChatSurfacePaneState {
  /** The open artifact's kind; null when the artifact surface has no tab. */
  artifactKind: ChatShellArtifactKind | null;
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  panelOpen: boolean;
  /** The raw incoming `surface` param — the kind-unknown tiebreak only. */
  rawSurface: string | undefined;
  surface: "artifact" | "gallery" | "target-accounts" | "plan";
}

export interface ChatSurfacePaneParams {
  edit: string | undefined;
  selection: string | undefined;
  surface: string | undefined;
}

const NO_PANE_PARAMS: ChatSurfacePaneParams = {
  edit: undefined,
  selection: undefined,
  surface: undefined,
};

export function chatSurfacePaneParams(
  state: ChatSurfacePaneState,
): ChatSurfacePaneParams {
  // Rail closed → the clean URL. The resting state carries NO pane params
  // (controller ruling); `?surface=chat` is its accepted inbound alias.
  if (!state.panelOpen) return NO_PANE_PARAMS;
  if (state.surface === "plan") return { ...NO_PANE_PARAMS, surface: "plan" };
  if (state.surface === "gallery") {
    // edit/selection are artifact-surface vocabulary — the parse only honors
    // them there, so the gallery never carries them.
    return { ...NO_PANE_PARAMS, surface: "gallery" };
  }
  if (state.surface === "target-accounts") {
    // Same rule as the gallery: the surface names itself and carries no
    // artifact vocabulary.
    return { ...NO_PANE_PARAMS, surface: "target-accounts" };
  }
  const surface =
    state.artifactKind ??
    // No open artifact yet (a deep link can land on the artifact surface
    // before a tab exists): preserve the incoming kind rather than rewriting
    // `ad` → `web` at mount.
    (state.rawSurface === "web" || state.rawSurface === "ad"
      ? state.rawSurface
      : "web");
  return {
    edit: state.editing ? "1" : undefined,
    // `canvas` is the parse default — omitted so the shared URL stays minimal.
    selection:
      state.editing && state.inspectorSelection !== "canvas"
        ? state.inspectorSelection
        : undefined,
    surface,
  };
}
