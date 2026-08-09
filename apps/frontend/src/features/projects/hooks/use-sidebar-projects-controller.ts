"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useChatRepositories } from "../data/projects-transport";
import { createSidebarProjectsRepository } from "../data/sidebar-projects.repository";
import type { SidebarProject } from "../model/sidebar-project";

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
  const sidebar = useMemo(
    () => createSidebarProjectsRepository(repositories),
    [repositories],
  );
  const [projects, setProjects] = useState<SidebarProject[]>([]);
  const [menuProjectId, setMenuProjectId] = useState<string | null>(null);
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const [editProjectName, setEditProjectName] = useState("");

  const reload = useCallback(async () => {
    const response = await sidebar.list();
    setProjects(response.data);
  }, [sidebar]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await sidebar.list();
      if (!cancelled) setProjects(response.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [sidebar]);

  const editProject = useMemo(
    () => projects.find((project) => project.id === editProjectId) ?? null,
    [editProjectId, projects],
  );

  useEffect(() => {
    if (!menuProjectId && !editProjectId) return;

    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setMenuProjectId(null);
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

  function togglePinned(projectId: string) {
    updateProject(projectId, (project) => ({
      ...project,
      pinned: !project.pinned,
    }));
    setMenuProjectId(null);
  }

  function beginEditProject(projectId: string) {
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    setEditProjectId(project.id);
    setEditProjectName(project.title);
    setMenuProjectId(null);
  }

  function cancelEditProject() {
    setEditProjectId(null);
    setEditProjectName("");
  }

  function saveEditProject() {
    const nextName = editProjectName.trim();
    if (!editProjectId || !nextName) return;
    // Project rename is not served: the as-built contract keeps project
    // lifecycle outside the chat shell (item 9), so this stays a local edit
    // until a project surface exists. It is not written anywhere.
    updateProject(editProjectId, (project) => ({
      ...project,
      title: nextName,
    }));
    cancelEditProject();
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

  function removeProject() {
    if (!editProjectId) return;
    setProjects((current) =>
      current.filter((project) => project.id !== editProjectId),
    );
    cancelEditProject();
  }

  return {
    activePathname: pathname,
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
    menuProjectId,
    projects,
    removeProject,
    saveEditProject,
    setEditProjectName,
    toggleMenu,
    togglePinned,
    toggleProject,
  };
}

export type SidebarProjectsController = ReturnType<
  typeof useSidebarProjectsController
>;
