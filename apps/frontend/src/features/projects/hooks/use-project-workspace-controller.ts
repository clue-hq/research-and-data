import { useMemo, useState } from "react";
import type { ProjectEntity, ProjectWorkspace } from "../model/project-workspace";

export interface ProjectWorkspaceInitialState {
  threadId?: string;
}

/**
 * Local interaction state for the real project shell.
 *
 * Artifact editing, project phases, and questionnaire answers remain absent.
 * R8 adds only server-advertised account/contact references and the one real
 * promoted agent profile; neither catalog is manufactured by this controller.
 */
export function useProjectWorkspaceController(workspace: ProjectWorkspace) {
  const [prompt, setPrompt] = useState("");
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntityIds, setSelectedEntityIds] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState(
    workspace.defaultAgentProfileId ?? workspace.models[0]?.id ?? "",
  );
  const [focusPane, setFocusPane] =
    useState<"artifacts" | "conversation" | "split">("split");
  const selectedEntities = useMemo(
    () => selectedEntityIds
      .map((id) => workspace.entities.find((entity) => entity.id === id))
      .filter((entity): entity is ProjectEntity => Boolean(entity)),
    [selectedEntityIds, workspace.entities],
  );
  const selectedModel =
    workspace.models.find((model) => model.id === selectedModelId) ??
    workspace.models[0];

  return {
    focusPane,
    modelPickerOpen,
    prompt,
    removeEntity(entityId: string) {
      setSelectedEntityIds((current) => current.filter((id) => id !== entityId));
    },
    resetSubmissionContext() {
      setSelectedEntityIds([]);
    },
    selectEntity(entityId: string) {
      setSelectedEntityIds((current) =>
        current.includes(entityId) ? current : [...current, entityId],
      );
    },
    selectedEntities,
    selectedEntityIds,
    selectedModel,
    selectModel(modelId: string) {
      setSelectedModelId(modelId);
      setModelPickerOpen(false);
    },
    setPrompt,
    toggleModelPicker() {
      setModelPickerOpen((current) => !current);
    },
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
