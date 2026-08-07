"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { sidebarProjectFixtures } from "../data/sidebar-projects.fixture";
import {
  SidebarProjectsResponseSchema,
  type SidebarProject,
} from "../model/sidebar-project";

function createInitialProjects() {
  return SidebarProjectsResponseSchema.parse({
    data: sidebarProjectFixtures,
    meta: { total: sidebarProjectFixtures.length },
  }).data;
}

export function useSidebarProjectsController() {
  const pathname = usePathname();
  const router = useRouter();
  const [projects, setProjects] = useState<SidebarProject[]>(createInitialProjects);
  const [menuProjectId, setMenuProjectId] = useState<string | null>(null);
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const [editProjectName, setEditProjectName] = useState("");

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

  function createConversation(projectId: string) {
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;

    const nextId = `thread-draft-${Date.now()}`;
    const nextHref = `${project.href}?thread=${nextId}`;

    updateProject(projectId, (project) => {
      return {
        ...project,
        expanded: true,
        conversations: [
          ...project.conversations,
          {
            href: nextHref,
            id: nextId,
            status: "idle",
            title: "New chat",
          },
        ],
      };
    });

    setMenuProjectId(null);
    router.push(nextHref);
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

    updateProject(editProjectId, (project) => ({
      ...project,
      title: nextName,
    }));
    cancelEditProject();
  }

  function archiveProjectChats(projectId: string) {
    updateProject(projectId, (project) => ({
      ...project,
      conversations: [],
      expanded: false,
    }));
    setMenuProjectId(null);
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
    archiveProjectChats,
    beginEditProject,
    cancelEditProject,
    closeMenu,
    createConversation,
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
