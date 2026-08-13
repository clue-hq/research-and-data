"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ProjectEntity, ProjectWorkspace } from "../model/project-workspace";
import {
  deleteChatContextHandoff,
  mergeComposerContextEntities,
  readChatContextHandoff,
  remainingComposerContextEntities,
  updateChatContextHandoffEntities,
} from "../model/chat-context-handoff";

export interface ProjectWorkspaceInitialState {
  handoffId?: string;
  focusPane?: ProjectWorkspaceFocusPane;
  threadId?: string;
}

export type ProjectWorkspaceFocusPane =
  | "artifacts"
  | "conversation"
  | "split";

export function initialWorkspaceFocusPane(
  artifactCount: number,
  requested?: ProjectWorkspaceFocusPane,
): ProjectWorkspaceFocusPane {
  if (requested) return requested;
  return artifactCount === 0 ? "conversation" : "split";
}

/**
 * Local interaction state for the real project shell.
 *
 * Artifact editing, project phases, and questionnaire answers remain absent.
 * R8 adds only server-advertised account/contact references and the one real
 * promoted agent profile; neither catalog is manufactured by this controller.
 */
export function useProjectWorkspaceController(
  workspace: ProjectWorkspace,
  initial: ProjectWorkspaceInitialState = {},
) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [prompt, setPrompt] = useState("");
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [selectedEntities, setSelectedEntities] = useState<ProjectEntity[]>([]);
  const submissionCleanupRequested = useRef(false);
  const [contextHandoffError, setContextHandoffError] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState(
    workspace.defaultAgentProfileId ?? workspace.models[0]?.id ?? "",
  );
  const [focusPane, setFocusPane] = useState<ProjectWorkspaceFocusPane>(() =>
    initialWorkspaceFocusPane(workspace.artifacts.length, initial.focusPane),
  );
  const composerEntities = useMemo(
    () => mergeComposerContextEntities(workspace.entities, selectedEntities),
    [selectedEntities, workspace.entities],
  );
  const selectedEntityIds = useMemo(
    () => selectedEntities.map((entity) => entity.id),
    [selectedEntities],
  );
  const selectedModel =
    workspace.models.find((model) => model.id === selectedModelId) ??
    workspace.models[0];

  useEffect(() => {
    if (!initial.handoffId) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const handoff = readChatContextHandoff(
        window.sessionStorage,
        initial.handoffId!,
        { projectId: workspace.id, threadId: initial.threadId },
      );
      if (!handoff) {
        setContextHandoffError(
          "The selected records could not be restored. Add them again before sending this message.",
        );
        return;
      }
      setSelectedEntities(handoff.entities);
      setContextHandoffError(null);
    });
    return () => {
      cancelled = true;
    };
  }, [initial.handoffId, initial.threadId, workspace.id]);

  useEffect(() => {
    if (!submissionCleanupRequested.current) return;
    submissionCleanupRequested.current = false;
    if (typeof window === "undefined" || !initial.handoffId) return;

    if (selectedEntities.length) {
      updateChatContextHandoffEntities(
        window.sessionStorage,
        initial.handoffId,
        selectedEntities,
      );
      return;
    }

    deleteChatContextHandoff(window.sessionStorage, initial.handoffId);
    const query = new URLSearchParams(searchParams.toString());
    query.delete("handoff");
    router.replace(`${pathname}${query.size ? `?${query.toString()}` : ""}`);
  }, [
    initial.handoffId,
    pathname,
    router,
    searchParams,
    selectedEntities,
  ]);

  return {
    composerEntities,
    contextHandoffError,
    focusPane,
    modelPickerOpen,
    prompt,
    removeEntity(entityId: string) {
      setSelectedEntities((current) => {
        const next = current.filter((entity) => entity.id !== entityId);
        if (typeof window !== "undefined" && initial.handoffId) {
          updateChatContextHandoffEntities(
            window.sessionStorage,
            initial.handoffId,
            next,
          );
        }
        return next;
      });
    },
    completeSubmissionContext(submittedEntityIds: readonly string[]) {
      setSelectedEntities((current) =>
        remainingComposerContextEntities(current, submittedEntityIds),
      );
      if (initial.handoffId) submissionCleanupRequested.current = true;
    },
    selectEntity(entityId: string) {
      const entity = composerEntities.find((item) => item.id === entityId);
      if (!entity) return;
      setSelectedEntities((current) => {
        if (current.some((item) => item.id === entityId)) return current;
        const next = [...current, entity];
        if (typeof window !== "undefined" && initial.handoffId) {
          updateChatContextHandoffEntities(
            window.sessionStorage,
            initial.handoffId,
            next,
          );
        }
        return next;
      });
    },
    selectedEntities,
    selectedEntityIds,
    selectedModel,
    selectModel(modelId: string) {
      setSelectedModelId(modelId);
      setModelPickerOpen(false);
    },
    setPrompt,
    showSplitWorkspace() {
      setFocusPane("split");
    },
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
