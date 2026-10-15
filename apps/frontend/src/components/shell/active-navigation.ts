/**
 * Which top-level navigation item a project route highlights (2026-10-15).
 *
 * The projects list highlights "Projects" and Home highlights "Home". Inside a project nothing at
 * the top level is highlighted: on a chat page the chat's own row in the project tree is the
 * highlight, and highlighting "Projects" as well would point at two places at once.
 */
export function projectRouteActiveHref(pathname: string): string | null {
  if (pathname === "/") return "/";
  if (pathname === "/projects" || pathname === "/projects/") return "/projects";
  return null;
}
