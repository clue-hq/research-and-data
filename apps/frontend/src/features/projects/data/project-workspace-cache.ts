import type { ProjectWorkspace } from "../model/project-workspace";

/**
 * The last project read per project id, for this browser tab (2026-10-15).
 *
 * The chat page remounts for every chat by design, and each remount read the project again
 * before showing anything ("Loading project…", ~0.8 s). The loader now shows the project a
 * previous mount read at once and still reads it again in the background — the newest read
 * replaces this entry, and a failed read removes it. Bounded; cleared with the page.
 */
const MAX_PROJECTS = 20;
const cache = new Map<string, ProjectWorkspace>();

export function cachedProjectWorkspace(projectId: string): ProjectWorkspace | null {
  return cache.get(projectId) ?? null;
}

export function rememberProjectWorkspace(workspace: ProjectWorkspace): void {
  cache.delete(workspace.id);
  cache.set(workspace.id, workspace);
  while (cache.size > MAX_PROJECTS) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

export function forgetProjectWorkspace(projectId: string): void {
  cache.delete(projectId);
}

export function clearProjectWorkspaceCache(): void {
  cache.clear();
}
