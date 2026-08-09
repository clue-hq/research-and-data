import { useState } from "react";

export interface ProjectWorkspaceInitialState {
  threadId?: string;
}

/**
 * Local interaction state for the real project shell.
 *
 * Artifact editing, project phases, model selection, questionnaire answers,
 * and fixture context are intentionally absent. None is a current backend
 * capability, so none may be manufactured by the workspace controller.
 */
export function useProjectWorkspaceController() {
  const [prompt, setPrompt] = useState("");
  const [focusPane, setFocusPane] =
    useState<"artifacts" | "conversation" | "split">("split");

  return {
    focusPane,
    prompt,
    setPrompt,
    toggleArtifactFocus() {
      setFocusPane((current) =>
        current === "artifacts" ? "split" : "artifacts",
      );
    },
    toggleConversationFocus() {
      setFocusPane((current) =>
        current === "conversation" ? "split" : "conversation",
      );
    },
  };
}
