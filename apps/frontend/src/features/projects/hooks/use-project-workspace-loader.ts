import { useEffect, useState } from "react";
import {
  cachedProjectWorkspace,
  forgetProjectWorkspace,
  rememberProjectWorkspace,
} from "../data/project-workspace-cache";
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
  // A project a previous mount read is shown at once; the effect below still reads it again and
  // the newest read wins (switching chats within a project, 2026-10-15).
  const fresh = (): ProjectWorkspaceLoadState => {
    const cached = httpMode ? cachedProjectWorkspace(projectId) : null;
    return {
      error: null,
      loading: httpMode && cached === null,
      projectId,
      workspace: cached ?? initialWorkspace,
    };
  };
  const [loaded, setLoaded] = useState<ProjectWorkspaceLoadState>(fresh);

  const current = loaded.projectId === projectId ? loaded : fresh();

  useEffect(() => {
    if (!httpMode) return;
    let cancelled = false;
    void repositories.projects
      .get(projectId)
      .then((next) => {
        rememberProjectWorkspace(next);
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
        forgetProjectWorkspace(projectId);
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
