"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useChatRepositories } from "../data/projects-transport";
import type { SidebarProject } from "../model/sidebar-project";
import { useProjectCatalogInvalidation } from "../model/project-catalog-invalidation";

/**
 * Folds a reload's server truth over the tree's local view state.
 *
 * Expansion is a purely local affordance — nothing durable records which
 * folders a reader opened — so a reload keeps it; every other field, `pinned`
 * included, is the server's answer and replaces what the browser held.
 */
export function mergeExpandedState(
  current: SidebarProject[],
  data: SidebarProject[],
): SidebarProject[] {
  const expanded = new Map(current.map((project) => [project.id, project.expanded]));
  return data.map((project) => ({
    ...project,
    expanded: expanded.get(project.id) ?? project.expanded,
  }));
}

/**
 * The sidebar tree.
 *
 * It reads through the repository seam (`frontend.md`:95) rather than importing
 * a fixture — the bypass charter §2 catalogued. Thread creation, rename, pin and
 * archive are governed mutations against the thread repository, so a sidebar
 * action is the same durable act the conversation header performs, and the
 * status badges are the server's derived precedence rather than a local guess.
 */
export function useSidebarProjectsController() {
  const pathname = usePathname();
  const router = useRouter();
  const repositories = useChatRepositories();
  const catalogInvalidation = useProjectCatalogInvalidation();
  const sidebar = repositories.sidebar;
  // Pin and archive are durable against both transports now that the directory
  // repository has a fixture adapter as well as an HTTP one, so the sidebar no
  // longer hides them behind a mode check.
  const projectMutationsAvailable = true;
  const projectRenameAvailable = repositories.transport.mode === "http";
  const [projects, setProjects] = useState<SidebarProject[]>([]);
  const [menuProjectId, setMenuProjectId] = useState<string | null>(null);
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const [editProjectName, setEditProjectName] = useState("");
  const [editProjectError, setEditProjectError] = useState<string | null>(null);
  const [savingProject, setSavingProject] = useState(false);
  const saveInFlight = useRef(false);

  const receiveProjects = useCallback((data: SidebarProject[]) => {
    setProjects((current) => mergeExpandedState(current, data));
  }, []);

  const reload = useCallback(async () => {
    const response = await sidebar.list();
    receiveProjects(response.data);
  }, [receiveProjects, sidebar]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await sidebar.list();
      if (!cancelled) receiveProjects(response.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [catalogInvalidation.revision, pathname, receiveProjects, sidebar]);

  const editProject = useMemo(
    () => projects.find((project) => project.id === editProjectId) ?? null,
    [editProjectId, projects],
  );

  useEffect(() => {
    if (!menuProjectId && !editProjectId) return;

    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setMenuProjectId(null);
      if (saveInFlight.current) return;
      setEditProjectId(null);
    }

    function handlePointerDown(event: PointerEvent) {
      if (!menuProjectId) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest("[data-sidebar-project-menu-root]")
      ) {
        return;
      }
      setMenuProjectId(null);
    }

    document.addEventListener("keydown", handleEscape);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [editProjectId, menuProjectId]);

  function updateProject(
    projectId: string,
    updater: (project: SidebarProject) => SidebarProject,
  ) {
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId ? updater(project) : project,
      ),
    );
  }

  function toggleProject(projectId: string) {
    updateProject(projectId, (project) => ({
      ...project,
      expanded: !project.expanded,
    }));
  }

  function toggleMenu(projectId: string) {
    setMenuProjectId((current) => (current === projectId ? null : projectId));
  }

  function closeMenu() {
    setMenuProjectId(null);
  }

  async function createConversation(projectId: string) {
    setMenuProjectId(null);
    const thread = await repositories.threads.create({ projectId });
    updateProject(projectId, (project) => ({ ...project, expanded: true }));
    await reload();
    router.push(thread.href);
  }

  async function togglePinned(projectId: string) {
    setMenuProjectId(null);
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    try {
      await repositories.directory.update(projectId, { pinned: !project.pinned });
      await reload();
      catalogInvalidation.invalidate();
    } catch (failure) {
      setEditProjectError(
        failure instanceof Error
          ? failure.message
          : "Your change could not be saved. Please try again.",
      );
    }
  }

  function beginEditProject(projectId: string) {
    if (!projectRenameAvailable) return;
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    setEditProjectId(project.id);
    setEditProjectName(project.title);
    setEditProjectError(null);
    setMenuProjectId(null);
  }

  function cancelEditProject() {
    if (saveInFlight.current) return;
    setEditProjectId(null);
    setEditProjectName("");
    setEditProjectError(null);
  }

  async function saveEditProject() {
    if (!projectRenameAvailable || saveInFlight.current) return;
    const nextName = editProjectName.trim();
    if (!editProjectId || !nextName || nextName.length > 200) return;
    saveInFlight.current = true;
    setSavingProject(true);
    setEditProjectError(null);
    try {
      const saved = await repositories.projects.rename(editProjectId, nextName);
      updateProject(saved.id, (project) => ({ ...project, title: saved.title }));
      setEditProjectId(null);
      setEditProjectName("");
      catalogInvalidation.invalidate();
    } catch (failure) {
      setEditProjectError(
        failure instanceof Error
          ? failure.message
          : "Unable to rename this project. Please try again.",
      );
    } finally {
      saveInFlight.current = false;
      setSavingProject(false);
    }
  }

  async function archiveProject() {
    if (!editProjectId || saveInFlight.current) return;
    saveInFlight.current = true;
    setSavingProject(true);
    setEditProjectError(null);
    try {
      await repositories.directory.setArchived(editProjectId, true);
      setEditProjectId(null);
      setEditProjectName("");
      await reload();
      catalogInvalidation.invalidate();
    } catch (failure) {
      setEditProjectError(
        failure instanceof Error
          ? failure.message
          : "Your change could not be saved. Please try again.",
      );
    } finally {
      saveInFlight.current = false;
      setSavingProject(false);
    }
  }

  async function archiveProjectChats(projectId: string) {
    setMenuProjectId(null);
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    // Per-thread archive is the as-built contract (item 2); the proposal's bulk
    // archive-all endpoint does not exist, so the sidebar action archives each
    // visible thread rather than pretending one call did.
    for (const conversation of project.conversations) {
      await repositories.threads.archive({ projectId, threadId: conversation.id });
    }
    await reload();
  }
  return {
    activePathname: pathname,
    archiveProject: () => {
      void archiveProject();
    },
    archiveProjectChats: (projectId: string) => {
      void archiveProjectChats(projectId);
    },
    beginEditProject,
    cancelEditProject,
    closeMenu,
    createConversation: (projectId: string) => {
      void createConversation(projectId);
    },
    editProject,
    editProjectName,
    editProjectError,
    savingProject,
    canSaveProject: Boolean(editProjectName.trim())
      && editProjectName.trim().length <= 200
      && !savingProject,
    menuProjectId,
    projects,
    projectMutationsAvailable,
    projectRenameAvailable,
    saveEditProject: () => {
      void saveEditProject();
    },
    setEditProjectName,
    toggleMenu,
    togglePinned: (projectId: string) => {
      void togglePinned(projectId);
    },
    toggleProject,
  };
}

export type SidebarProjectsController = ReturnType<
  typeof useSidebarProjectsController
>;
