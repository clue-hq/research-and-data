import { useEffect, useState } from "react";
import { useChatRepositories } from "../data/projects-transport";
import type { ProjectWorkspace } from "../model/project-workspace";
import { useProjectCatalogInvalidation } from "../model/project-catalog-invalidation";

interface ProjectWorkspaceLoadState {
  error: string | null;
  loading: boolean;
  projectId: string;
  workspace: ProjectWorkspace | null;
}

export function useProjectWorkspaceLoader({
  initialWorkspace,
  projectId,
}: {
  initialWorkspace: ProjectWorkspace | null;
  projectId: string;
}) {
  const repositories = useChatRepositories();
  const { revision } = useProjectCatalogInvalidation();
  const httpMode = repositories.transport.mode === "http";
  const [loaded, setLoaded] = useState<ProjectWorkspaceLoadState>({
    error: null,
    loading: httpMode,
    projectId,
    workspace: initialWorkspace,
  });

  const current = loaded.projectId === projectId
    ? loaded
    : {
        error: null,
        loading: httpMode,
        projectId,
        workspace: initialWorkspace,
      };

  useEffect(() => {
    if (!httpMode) return;
    let cancelled = false;
    void repositories.projects
      .get(projectId)
      .then((next) => {
        if (!cancelled) {
          setLoaded({
            error: null,
            loading: false,
            projectId,
            workspace: next,
          });
        }
      })
      .catch((failure: unknown) => {
        if (cancelled) return;
        setLoaded({
          error: failure instanceof Error
            ? failure.message
            : "Unable to load this project.",
          loading: false,
          projectId,
          workspace: null,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [httpMode, projectId, repositories.projects, revision]);

  return current;
}
