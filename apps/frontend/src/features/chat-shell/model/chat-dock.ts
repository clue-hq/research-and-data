import type { ChatSubmissionResult } from "@/features/projects/hooks/use-project-chat-controller";
import type { ChatShellArtifactKind } from "./chat-shell";
import type { EditorShellSurface } from "../hooks/use-editor-shell-controller";

// The chats route's dock choreography (founder ruling R6, 2026-08-17), as pure
// decisions so they are testable under the repo's DOM-less `tsx --test` runner.
// The chat surface consumes these directly — there is no second copy of the
// rule in the component.
//
// R6: while EDITING an open artifact, the inspector replaces the conversation
// column in `.chatBody` (the composer stays docked below, untouched). Entry is
// Edit-only; a message accepted by the agent dismisses the dock and restores
// the conversation.

export interface ChatDockState {
  /** Null until a real artifact tab is open — the chats route deliberately
   * fabricates no default tab, so `?surface=web&edit=1` alone must NOT empty
   * the chat body. */
  artifactKind: ChatShellArtifactKind | null;
  editing: boolean;
  panelOpen: boolean;
  surface: EditorShellSurface;
}

/** What `.chatBody` renders. `"conversation"` is the resting state. */
export type ChatDockContent =
  | "ad-inspector"
  | "conversation"
  | "site-inspector"
  | "web-inspector";

/** The dock is open only on the artifact surface, with the rail open, while
 * editing, and only once an artifact kind is actually known. */
export function chatDockOpen(state: ChatDockState): boolean {
  return (
    state.panelOpen &&
    state.surface === "artifact" &&
    state.editing &&
    state.artifactKind !== null
  );
}

export function chatDockContent(state: ChatDockState): ChatDockContent {
  if (!chatDockOpen(state)) return "conversation";
  if (state.artifactKind === "web") return "web-inspector";
  if (state.artifactKind === "site") return "site-inspector";
  return "ad-inspector";
}

/** Dismiss-on-send: only a submission the agent ACCEPTED closes the dock. A
 * refused send (`failed`) or an empty/threadless one (`not_submitted`) leaves
 * the user where they were — mid-edit. */
export function chatDockDismissedBySubmission(
  status: ChatSubmissionResult["status"],
): boolean {
  return status === "accepted";
}
